"""R2 공격(IP 교체 크리덴셜 스터핑) 테스트. 실제 gateway는 부르지 않는다."""
from fastapi.testclient import TestClient

from app import main, red_r2


def test_rotates_ip_every_request():
    # IP를 매 요청 갈아끼워 한 IP에 실패가 몰리지 않아야(R1 회피) 한다
    assert len(red_r2.SIM_IP_POOL) >= 2
    assert "admin123" in red_r2.COMMON_PASSWORDS  # 실제 비번이 섞여 있어야 탈취 장면이 난다


def test_run_cred_stuff_starts(monkeypatch):
    monkeypatch.setattr(main, "run_cred_stuff", lambda: {"run_id": "x", "stolen": False, "blocked": 0})
    r = TestClient(main.app).post("/run", json={"mode": "cred_stuff"})
    assert r.status_code == 202
    assert r.json() == {"mode": "cred_stuff", "status": "started"}
