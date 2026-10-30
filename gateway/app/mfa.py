"""R6 번호 일치(number matching). detector가 numbermatch:<account> 플래그를 세우면,
그 계정의 MFA 승인은 서버에만 있는 번호를 맞혀야 bank로 넘어간다.

승인 요청 본문에는 request_id만 있어서, 요청 때 request_id -> 계정을 Redis에 적어 둔다.
"""
import json
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from . import events
from .quarantine import mfa_number_key, numbermatch_key

REQUEST_PATH = "/api/v1/mfa/request"
APPROVE_PATH = "/api/v1/mfa/approve"
TTL = 600


def request_key(request_id: str) -> str:
    return f"mfa_req:{request_id}"


async def remember_request(body: bytes, account: str) -> None:
    """bank가 승인 요청을 만든 뒤. 플래그가 선 계정이면 이번 요청의 번호도 새로 뽑아 둔다."""
    try:
        request_id = str(json.loads(body).get("request_id", ""))
    except (ValueError, AttributeError):
        return
    if not request_id:
        return
    r = events.redis()
    await r.set(request_key(request_id), account, ex=TTL)
    if await r.exists(numbermatch_key(account)):
        # 실제로는 공격자 화면에 뜨고 사용자가 폰에 입력하는 숫자. 승인하는 사용자는 모름
        await r.set(mfa_number_key(account), f"{secrets.randbelow(90) + 10}", ex=TTL)


async def check_approve(request: Request) -> tuple[str | None, JSONResponse | None]:
    """승인 요청의 계정을 찾고, 번호 일치가 걸려 있는데 번호가 틀리면 막을 응답을 돌려준다."""
    try:
        data = json.loads(await request.body() or b"{}")
        request_id = str(data.get("request_id", ""))
        number = str(data.get("number", ""))
    except (ValueError, AttributeError):
        return None, None
    r = events.redis()
    account = await r.get(request_key(request_id))
    if account is None:
        return None, None
    account = account.decode() if isinstance(account, bytes) else account
    if not await r.exists(numbermatch_key(account)):
        return account, None
    expected = await r.get(mfa_number_key(account))
    expected = expected.decode() if isinstance(expected, bytes) else expected
    if expected is None or number != expected:
        return account, JSONResponse(
            {"error": "number_mismatch", "message": "로그인 화면에 표시된 번호를 입력해야 승인됩니다."},
            status_code=403)
    await r.delete(mfa_number_key(account))
    return account, None
