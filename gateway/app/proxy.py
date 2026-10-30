import os

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


async def shutdown() -> None:
    if _client:
        await _client.aclose()


async def forward(request: Request) -> Response:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _SKIP}
    upstream = await _client.request(
        request.method,
        request.url.path,
        params=request.query_params,
        headers=headers,
        content=await request.body(),
    )
    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _SKIP}
    return Response(upstream.content, status_code=upstream.status_code, headers=out_headers)
