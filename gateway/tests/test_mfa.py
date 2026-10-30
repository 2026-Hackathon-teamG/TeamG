import json

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient

from app import decoys, events, main, proxy, quarantine

IP = "203.0.113.24"
_seq = iter(range(1000))


def bank(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/mfa/request":
        return httpx.Response(200, json={"request_id": f"req{next(_seq)}"},
                              headers={"X-Mfa-Action": "request", "X-Login-Account": "kim.j"})
    if request.url.path == "/api/v1/mfa/approve":
        return httpx.Response(200, json={"approved": True, "user": "kim.j"},
                              headers={"X-Mfa-Action": "approve", "X-Login-Account": "kim.j"})
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

        def call(fn, *args):
            return client.portal.call(fn, *args)

        yield client, last_event, r, call


def post(client, path, body=None):
    return client.post(path, json=body or {}, headers={"X-Sim-IP": IP})


def test_mfa_action_recorded_in_event(ctx):
    client, last_event, _, _ = ctx
    req_id = post(client, "/api/v1/mfa/request").json()["request_id"]
    e = last_event()
    assert e["mfa_action"] == "request" and e["account"] == "kim.j"

    assert post(client, "/api/v1/mfa/approve", {"request_id": req_id}).status_code == 200
    assert last_event()["mfa_action"] == "approve"


def test_numbermatch_blocks_approve_without_number(ctx):
    client, last_event, r, call = ctx
    call(r.set, quarantine.numbermatch_key("kim.j"), "R6")
    req_id = post(client, "/api/v1/mfa/request").json()["request_id"]

    resp = post(client, "/api/v1/mfa/approve", {"request_id": req_id})
    assert resp.status_code == 403        # 번호 모르는 사용자의 피로 승인은 막힘
    e = last_event()
    assert e["mfa_action"] == "approve" and e["account"] == "kim.j" and e["status"] == 403

    number = call(r.get, quarantine.mfa_number_key("kim.j")).decode()
    assert post(client, "/api/v1/mfa/approve", {"request_id": req_id, "number": number}).status_code == 200
