"""MFA 요청 폭주를 막는 차단 룰.

- R6: 같은 계정이 짧은 시간(WINDOW)에 MFA 요청을 THRESHOLD회 넘게 보내면,
  그 계정에 번호 일치(number matching) 플래그를 세운다. 이후 요청부터는
  화면 번호를 입력해야 승인되게 gateway가 막는다.

defense.py의 로그인 차단(R1·R2)과 같은 구조다. 대상만 IP→계정, 기준만
로그인 실패→MFA 요청으로 바뀐 것뿐이다.

플래그 상태도 Redis 키(numbermatch:<account>)에 TTL과 함께 두고,
메모리에는 요청 시각만 둔다. detector를 재시작하면 창은 비지만
이미 올린 플래그는 Redis에 남는다.
"""
import logging
from collections import defaultdict, deque
from datetime import datetime

from shared import Event

from . import hub, rds

log = logging.getLogger(__name__)

# WINDOW초에 MFA 요청을 THRESHOLD회 넘기면 번호 일치를 요구
WINDOW = 600
THRESHOLD = 3
NUMBERMATCH_SECONDS = 600

_requests: dict[str, deque[datetime]] = defaultdict(deque)  # account -> 요청 시각


def reset() -> None:
    _requests.clear()


def _recent_request_count(account: str, now: datetime) -> int:
    reqs = _requests[account]
    reqs.append(now)
    cutoff = now.timestamp() - WINDOW
    while reqs and reqs[0].timestamp() < cutoff:
        reqs.popleft()
    return len(reqs)


async def process(e: Event) -> None:
    """MFA 요청 이벤트만 본다. 임계치를 넘으면 계정에 번호 일치를 요구한다."""
    if e.mfa_action != "request":
        return
    if not e.account:
        return
    if _recent_request_count(e.account, e.ts) < THRESHOLD:
        return

    # Redis에 이미 플래그가 서 있는지 먼저 물어보고 세운다. 그래야 TTL이
    # 만료된 뒤 다시 임계치를 넘겼을 때도 재방송이 된다.
    already_flagged = await rds.client.exists(rds.numbermatch_key(e.account))
    await rds.client.set(rds.numbermatch_key(e.account), "R6", ex=NUMBERMATCH_SECONDS)
    if not already_flagged:
        await hub.broadcast(
            "numbermatch",
            {"account": e.account, "rule": "R6", "seconds": NUMBERMATCH_SECONDS},
        )