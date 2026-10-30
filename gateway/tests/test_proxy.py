import asyncio

import httpx

from app import proxy


def test_upstream_cookie_is_not_kept_between_users():
    async def run() -> int:
        await proxy.startup()
        proxy._client._transport = httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"set-cookie": "sessionid=a; Path=/"})
        )
        await proxy._client.get("/login")
        kept = len(proxy._client.cookies.jar)
        await proxy.shutdown()
        return kept

    assert asyncio.run(run()) == 0


def test_client_forwarded_headers_are_not_sent_upstream():
    # R2: 클라이언트가 보낸 X-Forwarded-*·X-Real-IP는 bank로 넘기지 않는다
    for h in ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip"):
        assert h in proxy._SKIP
