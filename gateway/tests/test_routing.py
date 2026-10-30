import json

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient

from app import decoys, events, main, proxy, quarantine

REAL_EMAIL = "real@example.com"
IP_A, IP_B, IP_C = "203.0.113.24", "198.51.100.7", "192.0.2.55"
INTERNAL = {"X-Internal-Request": "true"}


def bank(request: httpx.Request) -> httpx.Response:
    """bank 대역. 실제 bank와 같은 규칙만 흉내."""
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /admin-old\n")
    if path == "/api/v1/docs":
        return httpx.Response(200, html="<html><body><h1>API</h1></body></html>")
    if path == "/api/v1/customers":
        if request.headers.get("x-internal-request") != "true":
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(200, json={"id": 1001, "email": REAL_EMAIL})
    if path == "/login":
        return httpx.Response(200, headers=[("set-cookie", "sessionid=a; Path=/"),
                                            ("set-cookie", "csrftoken=b; Path=/")])
    return httpx.Response(404, text="not found")


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
        def set_decoys(on: bool):
            v = "1" if on else "0"
            flags = {"robots": v, "admin_legacy": v, "docs_bait": v, "endless_export": v}
            client.portal.call(lambda: r.hset(quarantine.DECOYS_KEY, mapping=flags))

        def last_event() -> dict:
            entries = client.portal.call(r.xrevrange, "events", "+", "-", 1)
            return json.loads(entries[0][1][b"data"])

        yield client, set_decoys, last_event


def get(client, path, ip, **kw):
    headers = {"X-Sim-IP": ip, **kw.pop("headers", {})}
    return client.get(path, headers=headers, **kw)


def test_decoys_off_passes_everything_to_bank(ctx):
    client, set_decoys, last_event = ctx
    set_decoys(False)
    assert "/admin-legacy" not in get(client, "/robots.txt", IP_A).text
    assert "/api/internal/export" not in get(client, "/api/v1/docs", IP_A).text
    assert get(client, "/admin-legacy", IP_A).status_code == 404
    assert get(client, "/api/internal/export", IP_A).status_code == 404
    r = get(client, "/api/v1/customers?id=1001", IP_A, headers=INTERNAL)
    assert r.json()["email"] == REAL_EMAIL
    assert last_event()["records_out"] == 1 and last_event()["routed_to"] == "bank"


def test_bait_injected_when_on(ctx):
    client, set_decoys, last_event = ctx
    set_decoys(True)
    assert "Disallow: /admin-legacy" in get(client, "/robots.txt", IP_A).text
    assert last_event()["decoy_id"] == "robots"
    docs = get(client, "/api/v1/docs", IP_A).text
    assert docs.count("/api/internal/export") == 2 and "<!--" in docs
    assert docs.index("/api/internal/export") < docs.index("</body>")


def test_admin_legacy_quarantines_ip(ctx):
    client, set_decoys, last_event = ctx
    set_decoys(True)
    r = get(client, "/admin-legacy", IP_A)
    assert r.status_code == 200 and "/api/internal/export?page=1" in r.text
    ev = last_event()
    assert ev["routed_to"] == "decoy" and ev["decoy_id"] == "admin_legacy" and ev["actor_id"] == "A-01"

    # 같은 IP → 가짜 고객, 다른 IP → 실제 bank
    fake = get(client, "/api/v1/customers?id=1001", IP_A, headers=INTERNAL).json()
    assert fake["email"].endswith("@a-01.trace.example")
    assert last_event()["routed_to"] == "decoy" and last_event()["actor_id"] == "A-01"
    assert get(client, "/api/v1/customers?id=1001", IP_B, headers=INTERNAL).json()["email"] == REAL_EMAIL

    # 격리돼도 bank와 같은 인증 규칙
    assert get(client, "/api/v1/customers?id=1001", IP_A).status_code == 401


def test_export_token_links_new_ip_to_same_actor(ctx):
    client, set_decoys, last_event = ctx
    set_decoys(True)
    body = get(client, "/api/internal/export?page=1", IP_A).json()
    assert len(body["records"]) == 50 and body["has_more"]
    assert all(rec["email"].endswith("@a-01.trace.example") for rec in body["records"])
    assert body["next_token"].startswith("pt_A-01_2_")
    assert last_event()["records_out"] == 50 and last_event()["actor_id"] == "A-01"

    # 다른 IP에서 토큰 재사용 → 같은 A-01, 2페이지, 그 IP도 격리
    body2 = get(client, "/api/internal/export", IP_B, params={"token": body["next_token"]}).json()
    assert body2["page"] == 2 and body2["next_token"].startswith("pt_A-01_3_")
    assert last_event()["actor_id"] == "A-01" and last_event()["ip"] == IP_B
    assert get(client, "/api/v1/customers?id=1001", IP_B, headers=INTERNAL).json()["email"].endswith("a-01.trace.example")


def test_forged_token_is_a_new_actor(ctx):
    client, set_decoys, last_event = ctx
    set_decoys(True)
    get(client, "/admin-legacy", IP_A)
    forged = "pt_A-01_9_0000000000000000"
    get(client, "/api/internal/export", IP_C, params={"token": forged})
    assert last_event()["actor_id"] == "A-02"


def test_fake_data_is_stable_per_actor(ctx):
    client, set_decoys, _ = ctx
    set_decoys(True)
    get(client, "/admin-legacy", IP_A)
    a = get(client, "/api/v1/customers?id=1500", IP_A, headers=INTERNAL).json()
    b = get(client, "/api/v1/customers?id=1500", IP_A, headers=INTERNAL).json()
    assert a == b


def test_multiple_set_cookie_kept(ctx):
    client, set_decoys, _ = ctx
    set_decoys(False)
    r = get(client, "/login", IP_A)
    cookies = [v for k, v in r.headers.multi_items() if k == "set-cookie"]
    assert len(cookies) == 2
