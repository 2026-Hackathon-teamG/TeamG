"""R3 공격(정찰+살포) 테스트. 실제 gateway는 부르지 않는다."""
from fastapi.testclient import TestClient

from app import main, red_r3


def test_uniform_responses_reveal_nothing():
    # R3로 모든 응답이 같으면(한 묶음) 아무 계정도 못 가린다
    sigs = {(401, '{"error":"unauthorized"}'): red_r3.CANDIDATE_USERNAMES}
    assert red_r3.enumerate_existing(sigs) == []


def test_different_responses_expose_minority():
    # 응답이 갈리면 소수파(다르게 반응한 계정)를 존재로 추정
    sigs = {
        (401, "no such account"): ["no.such", "ghost", "guest"],
        (401, "wrong password"): ["admin", "lee.s"],
    }
    assert red_r3.enumerate_existing(sigs) == ["admin", "lee.s"]


def test_run_recon_spray_starts(monkeypatch):
    monkeypatch.setattr(main, "run_recon_spray", lambda: {"run_id": "x", "enumerated": [], "stolen": []})
    r = TestClient(main.app).post("/run", json={"mode": "recon_spray"})
    assert r.status_code == 202
    assert r.json() == {"mode": "recon_spray", "status": "started"}
