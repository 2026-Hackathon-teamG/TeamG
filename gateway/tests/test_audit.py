import json

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient

from app import decoys, events, main, proxy, quarantine
from app.decoys import audit

IP_A = "203.0.113.24"
REAL_EMAIL = "real@example.com"
INTERNAL = {"X-Internal-Request": "true"}


def bank(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/":
        return httpx.Response(200, html="<html><body><h1>한결은행</h1></body></html>")
    if request.url.path == "/api/v1/customers":
        if request.headers.get("x-internal-request") != "true":
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(200, json={"id": 1001, "email": REAL_EMAIL})
    return httpx.Response(404, text="not found")


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setattr(decoys, "DELAY", (0, 0))
    r = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(events, "startup", _set(events, "_redis", r))
    monkeypatch.setattr(events, "shutdown", _noop)
    monkeypatch.setattr(proxy, "startup", _set(proxy, "_client",
                        httpx.AsyncClient(base_url="http://bank", transport=httpx.MockTransport(bank))))
    with TestClient(main.app) as client:
        def set_audit(on: bool):
            client.portal.call(lambda: r.hset(quarantine.DECOYS_KEY, mapping={"audit": "1" if on else "0"}))

        def key(kind, value):
            return client.portal.call(r.get, quarantine.key(kind, value))

        def last_event():
            entries = client.portal.call(r.xrevrange, "events", "+", "-", 1)
            return json.loads(entries[0][1][b"data"])

        yield client, set_audit, key, last_event


def _set(mod, attr, value):
    async def start():
        setattr(mod, attr, value)
    return start


async def _noop():
    pass


def test_audit_contact_quarantines_session_and_ip(ctx):
    client, set_audit, key, last_event = ctx
    set_audit(True)
    r = client.get(audit.PATH, headers={"X-Sim-IP": IP_A}, cookies={"sessionid": "S1"})
    assert r.status_code == 200 and r.json()["audit_id"] == "001"
    e = last_event()
    assert e["routed_to"] == "decoy" and e["decoy_id"] == "audit" and e["actor_id"] == "A-01"
    # 접촉으로 세션과 IP가 격리 목록에 오름
    assert key("session", "S1") == b"A-01"
    assert key("ip", IP_A) == b"A-01"
    # 격리된 세션의 고객 조회는 가짜 데이터
    fake = client.get("/api/v1/customers?id=1001", headers={**INTERNAL, "X-Sim-IP": "9.9.9.9"},
                      cookies={"sessionid": "S1"}).json()
    assert fake["email"].endswith("@a-01.trace.example")


def test_audit_path_passes_to_bank_when_off(ctx):
    client, set_audit, key, last_event = ctx
    set_audit(False)
    r = client.get(audit.PATH, headers={"X-Sim-IP": IP_A}, cookies={"sessionid": "S1"})
    assert r.status_code == 404                    # bank가 모르는 경로
    assert key("session", "S1") is None            # 격리 안 됨


def test_landing_page_gets_hidden_bait_when_on(ctx):
    client, set_audit, key, last_event = ctx
    set_audit(True)
    html = client.get("/", headers={"X-Sim-IP": IP_A}).text
    assert audit.HINT in html
    assert html.count(audit.PATH) >= 2             # 숨은 문단 + 주석
    assert "<h1>한결은행</h1>" in html             # 원본 유지


def test_landing_page_untouched_when_off(ctx):
    client, set_audit, key, last_event = ctx
    set_audit(False)
    assert audit.HINT not in client.get("/", headers={"X-Sim-IP": IP_A}).text
