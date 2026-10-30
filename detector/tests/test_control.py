import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import control


@pytest.fixture
def agent_calls(monkeypatch):
    """agent 실행(ops.demo_run)과 hub를 가짜로 바꿔 /api 라우터만 검증한다."""
    runs = []

    async def demo_run(body):
        runs.append(body.mode)
        return {"mode": body.mode, "status": "started"}

    async def noop_broadcast(*a, **k):
        return None

    monkeypatch.setattr(control.ops, "demo_run", demo_run)
    monkeypatch.setattr(control.hub, "broadcast", noop_broadcast)
    # 커서·플레이 상태 초기화
    control._step = control.LAST
    control._playing = False
    control._last_fired_round = 0
    return runs


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(control.router)
    return TestClient(app)


def test_state_matches_dashboard_contract(client, agent_calls):
    body = client.get("/api/state").json()
    # DashboardState 최상위 필수 필드
    for key in ("scenario", "round", "phase", "risk", "risk_level",
                "kpi", "techniques", "rules", "events", "rounds"):
        assert key in body, key
    for key in ("total_attempts", "attack_attempts", "breaches", "breach_rate",
                "rules_applied", "reattack_total", "reattack_blocked"):
        assert key in body["kpi"], key
    assert body["source"] == "live"


def test_reset_goes_to_first_step(client, agent_calls):
    resp = client.post("/api/control", json={"action": "reset"})
    assert resp.status_code == 200
    assert client.get("/api/state").json()["step"] == 0


def test_next_advances_one_step(client, agent_calls):
    client.post("/api/control", json={"action": "reset"})
    before = client.get("/api/state").json()["step"]
    client.post("/api/control", json={"action": "next"})
    assert client.get("/api/state").json()["step"] == before + 1


def test_next_round_advances_round_and_fires_agent(client, agent_calls):
    client.post("/api/control", json={"action": "reset"})   # step0 = round 0(idle)
    resp = client.post("/api/control", json={"action": "next_round"})
    body = resp.json()
    assert body["round"] == 1
    # 라운드 1 진입 → 해당 agent 모드 실행
    assert agent_calls == [control.ROUND_AGENT_MODE[1]]


def test_end_jumps_to_last(client, agent_calls):
    client.post("/api/control", json={"action": "reset"})
    client.post("/api/control", json={"action": "end"})
    state = client.get("/api/state").json()
    assert state["step"] == control.LAST
    assert state["phase"] == "done"


def test_event_seq_is_monotonic(client, agent_calls):
    client.post("/api/control", json={"action": "end"})
    events = client.get("/api/state").json()["events"]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
