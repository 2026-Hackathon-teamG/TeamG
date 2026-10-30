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
