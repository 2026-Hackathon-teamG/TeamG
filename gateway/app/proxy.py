import os
from http.cookiejar import DefaultCookiePolicy

import httpx
from fastapi import Request, Response

BANK_URL = os.environ.get("BANK_URL", "http://bank:8001")

# hop-by-hop 헤더와 길이·인코딩은 다시 계산되므로 넘기지 않음
_SKIP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
         "proxy-authorization", "proxy-authenticate", "host", "content-length", "content-encoding", "date", "server"}

_client: httpx.AsyncClient | None = None


async def startup() -> None:
    global _client
    _client = httpx.AsyncClient(base_url=BANK_URL, timeout=10.0)
    # 클라이언트 하나를 모든 사용자가 공유하므로 쿠키를 저장하면 세션이 섞인다.
    # 사용자 쿠키는 요청 헤더로 그대로 넘어가니 저장소는 비워 둔다.
    _client.cookies.jar.set_policy(DefaultCookiePolicy(allowed_domains=[]))


async def shutdown() -> None:
    if _client:
        await _client.aclose()


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
    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _SKIP}
    return Response(upstream.content, status_code=upstream.status_code, headers=out_headers)
