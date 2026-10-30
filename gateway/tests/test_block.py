import json

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient

from app import decoys, events, main, proxy, quarantine

IP = "203.0.113.24"


def bank(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/login":
        body = json.loads(request.content or b"{}")
        ok = body.get("username") == "admin" and body.get("password") == "admin123"
        status = 200 if ok else 401
        return httpx.Response(status, json={"user": body.get("username")} if ok else {"error": "unauthorized"},
                              headers={"X-Login-Result": "success" if ok else "fail",
                                       "X-Login-Account": str(body.get("username", "-"))})
    return httpx.Response(200, text="ok")


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setattr(decoys, "DELAY", (0, 0))
    r = fakeredis.aioredis.FakeRedis()

    async def fake_events_startup():
        events._redis = r

    async def fake_proxy_startup():
        proxy._client = httpx.AsyncClient(base_url="http://bank", transport=httpx.MockTransport(bank))

    async def noop():
        pass

    monkeypatch.setattr(events, "startup", fake_events_startup)
    monkeypatch.setattr(events, "shutdown", noop)
    monkeypatch.setattr(proxy, "startup", fake_proxy_startup)
    with TestClient(main.app) as client:
        def last_event() -> dict:
            entries = client.portal.call(r.xrevrange, "events", "+", "-", 1)
            return json.loads(entries[0][1][b"data"])

        def block(kind, value):
            client.portal.call(lambda: r.set(quarantine.block_key(kind, value), "R1"))

        yield client, last_event, block


def login(client, username, password):
    return client.post("/api/v1/login", json={"username": username, "password": password},
                       headers={"X-Sim-IP": IP})


def test_login_result_recorded_in_event(ctx):
    client, last_event, _ = ctx
    assert login(client, "admin", "wrong").status_code == 401
    e = last_event()
    assert e["login_result"] == "fail" and e["account"] == "admin" and e["path"] == "/api/v1/login"

    assert login(client, "admin", "admin123").status_code == 200
    assert last_event()["login_result"] == "success"


def test_blocked_ip_gets_429(ctx):
    client, last_event, block = ctx
    block("ip", IP)
    r = login(client, "admin", "admin123")
    assert r.status_code == 429            # 차단된 IP는 로그인 성공도 막힘
    assert last_event()["status"] == 429


def test_blocked_actor_gets_429(ctx):
    client, last_event, block = ctx
    block("actor", "A-01")
    # 토큰 서명으로 actor가 A-01로 확인되면 차단
    from shared import tokens
    token = tokens.sign("A-01", 1, quarantine.TOKEN_SECRET)
    r = client.get(f"/api/v1/customers?token={token}", headers={"X-Sim-IP": "198.51.100.7"})
    assert r.status_code == 429
