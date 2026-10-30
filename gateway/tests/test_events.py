from fastapi import Request

from app import events


def test_header_hash_depends_on_order_not_values():
    a = events.header_hash(["Host", "User-Agent", "Accept"])
    assert len(a) == 6
    assert a == events.header_hash(["host", "user-agent", "accept"])
    assert a != events.header_hash(["user-agent", "host", "accept"])


def test_sim_ip_only_in_demo_mode(monkeypatch):
    headers = {"x-sim-ip": "203.0.113.24", "x-agent-note": "판단"}

    monkeypatch.setenv("DEMO_MODE", "1")
    assert events.client_ip(headers, "172.18.0.1") == "203.0.113.24"
    assert events.agent_note(headers) == "판단"

    monkeypatch.setenv("DEMO_MODE", "0")
    assert events.client_ip(headers, "172.18.0.1") == "172.18.0.1"
    assert events.agent_note(headers) is None


def test_agent_note_restores_utf8(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    as_starlette_sees_it = "메인 확인".encode().decode("latin-1")
    assert events.agent_note({"x-agent-note": as_starlette_sees_it}) == "메인 확인"


def make_request(*headers: tuple[bytes, bytes]) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": list(headers),
                    "scheme": "http", "server": ("gateway", 8000), "client": ("172.18.0.1", 1234)})


def test_internal_header_flag_ignores_value():
    assert events.build(make_request(), 200).internal_header is False
    assert events.build(make_request((b"x-internal-request", b"false")), 200).internal_header is True


def test_client_ip_ignores_forwarded_headers(monkeypatch):
    # R2: 공격자가 보낸 X-Forwarded-For/X-Real-IP로 IP 판단을 바꿀 수 없어야 함
    monkeypatch.setenv("DEMO_MODE", "0")
    headers = {"x-forwarded-for": "9.9.9.9", "x-real-ip": "8.8.8.8"}
    assert events.client_ip(headers, "172.18.0.1") == "172.18.0.1"


def test_build_ip_ignores_forwarded_header(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "0")
    ev = events.build(make_request((b"x-forwarded-for", b"9.9.9.9")), 200)
    assert ev.ip == "172.18.0.1"
