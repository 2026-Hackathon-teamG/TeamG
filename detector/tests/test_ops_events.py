from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared import Event

from app import ops


def make_event() -> dict:
    return Event(id="evt_1", ts=datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc), ip="203.0.113.24",
                 method="GET", path="/api/v1/customers?id=1001", status=200, header_hash="abc123",
                 routed_to="bank", records_out=1).model_dump()


@pytest.fixture
def calls(monkeypatch):
    received = []

    async def list_events(since, limit):
        received.append((since, limit))
        return [make_event()]

    monkeypatch.setattr(ops.db, "list_events", list_events)
    return received


@pytest.fixture
def client():
    # detector 앱은 시작할 때 PostgreSQL에 연결하므로 라우터만 띄움
    app = FastAPI()
    app.include_router(ops.router)
    return TestClient(app)


def test_events_returns_event_format(client, calls):
    resp = client.get("/ops/events")
    assert resp.status_code == 200
    assert Event.model_validate(resp.json()[0]) == Event.model_validate(make_event())
    assert calls == [(None, 100)]


def test_events_passes_since_and_limit(client, calls):
    resp = client.get("/ops/events", params={"since": "2026-10-31T05:00:00Z", "limit": 50})
    assert resp.status_code == 200
    assert calls == [(datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc), 50)]


@pytest.mark.parametrize("params", [{"since": "not-a-date"}, {"limit": 0}, {"limit": 1001}])
def test_events_rejects_invalid_params(client, calls, params):
    assert client.get("/ops/events", params=params).status_code == 422
    assert calls == []
