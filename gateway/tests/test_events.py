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
