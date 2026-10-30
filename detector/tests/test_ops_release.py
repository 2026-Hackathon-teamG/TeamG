from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared import Actor

from app import ops, scoring

T0 = datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc)
IP = "203.0.113.24"


def test_release_clears_keys_and_score_and_sends_actor_format(monkeypatch):
    scoring.reset()
    scoring._states["A-01"] = scoring._states[IP] = scoring.State(first_seen=T0, last_seen=T0, score=60)
    deleted, sent, states_at_release = [], [], []

    class FakeRedis:
        async def delete(self, *keys):
            deleted.extend(keys)

    async def release_actor(actor_id):
        states_at_release.append(dict(scoring._states))
        return [("ip", IP)]

    async def get_actor(actor_id):
        return {"id": actor_id, "status": "released", "score": 60, "first_seen": T0, "last_seen": T0,
                "links": [], "timeline": []}

    async def broadcast(type_, data):
        sent.append((type_, data))

    monkeypatch.setattr(ops.rds, "client", FakeRedis())
    monkeypatch.setattr(ops.db, "release_actor", release_actor)
    monkeypatch.setattr(ops.db, "get_actor", get_actor)
    monkeypatch.setattr(ops.hub, "broadcast", broadcast)

    # detector 앱은 시작할 때 PostgreSQL에 연결하므로 라우터만 띄움
    app = FastAPI()
    app.include_router(ops.router)
    assert TestClient(app).post("/ops/actors/A-01/release").status_code == 200

    assert deleted == [f"quarantine:ip:{IP}"]
    assert states_at_release == [{}]    # DB를 바꾸기 전에 점수를 먼저 지움
    (type_, data), = sent
    assert type_ == "actor_update"
    assert Actor.model_validate(data).status == "released"
