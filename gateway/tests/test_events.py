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
