import os
from http.cookiejar import DefaultCookiePolicy

import httpx
from fastapi import Request, Response

BANK_URL = os.environ.get("BANK_URL", "http://bank:8001")

# hop-by-hop 헤더와 길이·인코딩은 다시 계산되므로 넘기지 않음.
# 클라이언트가 보낸 X-Forwarded-*·X-Real-IP도 버린다(R2): 공격자가 이 헤더로
# 자기 IP를 속여 bank나 탐지 엔진의 IP 판단을 흔들지 못하게 한다.
_SKIP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
         "proxy-authorization", "proxy-authenticate", "host", "content-length", "content-encoding", "date", "server",
         "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip"}

_client: httpx.AsyncClient | None = None


async def startup() -> None:
    global _client
    _client = httpx.AsyncClient(base_url=BANK_URL, timeout=10.0)
    # 클라이언트 하나를 모든 사용자가 공유하므로 쿠키를 저장하면 세션이 섞임.
    # 사용자 쿠키는 요청 헤더로 그대로 넘어가니 저장소는 비워 둠
    _client.cookies.jar.set_policy(DefaultCookiePolicy(allowed_domains=[]))


async def shutdown() -> None:
    if _client:
        await _client.aclose()


def _response(body: bytes, status: int, raw_headers: list[tuple[bytes, bytes]]) -> Response:
    resp = Response(body, status_code=status)
    # Set-Cookie처럼 같은 이름이 여러 번 오는 헤더를 합치지 않도록 raw로 붙임
    resp.raw_headers.extend((k, v) for k, v in raw_headers if k.decode().lower() not in _SKIP)
    return resp


def replace_body(resp: Response, body: bytes) -> Response:
    """미끼 주입용. 헤더는 유지하고 본문과 길이만 바꿈."""
    return _response(body, resp.status_code, resp.raw_headers)


async def forward(request: Request) -> Response:
    # 한글 같은 비 ASCII 헤더 값도 그대로 넘기도록 bytes 상태로 전달
    headers = [(k, v) for k, v in request.headers.raw if k.decode().lower() not in _SKIP]
    try:
        upstream = await _client.request(
            request.method,
            request.url.path,
            params=request.query_params,
            headers=headers,
            content=await request.body(),
        )
    except httpx.HTTPError:
        return Response("bad gateway", status_code=502)
    return _response(upstream.content, upstream.status_code, upstream.headers.raw)
