import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import hub, ops


class FakeWS:
    def __init__(self, fail=False, stall=False):
        self.sent, self.fail, self.stall, self.closed = [], fail, stall, False

    async def accept(self):
        pass

    async def send_text(self, text):
        if self.stall:
            await asyncio.Event().wait()
        if self.fail:
            raise RuntimeError("closed")
        self.sent.append(json.loads(text))

    async def close(self):
        self.closed = True


def test_broadcast_sends_and_drops_dead_clients():
    async def scenario():
        ok, dead = FakeWS(), FakeWS(fail=True)
        await hub.connect(ok)
        await hub.connect(dead)
        await hub.broadcast("event", {"path": "/고객"})
        assert ok.sent == [{"type": "event", "data": {"path": "/고객"}}]
        assert dead not in hub._clients
        assert dead.closed
        assert not ok.closed
        hub.disconnect(ok)
        assert not hub.has_clients()

    asyncio.run(scenario())


def test_slow_client_does_not_block_others(monkeypatch):
    monkeypatch.setattr(hub, "SEND_TIMEOUT", 0.01)

    async def scenario():
        ok, slow = FakeWS(), FakeWS(stall=True)
        await hub.connect(ok)
        await hub.connect(slow)
        await asyncio.wait_for(hub.broadcast("stats", {"real_leaks": 1}), timeout=1)
        assert ok.sent == [{"type": "stats", "data": {"real_leaks": 1}}]
        assert slow not in hub._clients
        assert slow.closed
        hub.disconnect(ok)

    asyncio.run(scenario())


@pytest.fixture
def client(monkeypatch):
    async def stats():
        return {"real_leaks": 0}

    monkeypatch.setattr(ops.db, "stats", stats)
    # detector 앱은 시작할 때 PostgreSQL에 연결하므로 라우터만 띄움
    app = FastAPI()
    app.include_router(ops.router)
    with TestClient(app) as test_client:
        yield test_client


def connect_stream(client):
    session = client.websocket_connect("/ops/stream")
    session.__enter__()
    assert session.receive_json() == {"type": "stats", "data": {"real_leaks": 0}}
    return session


def test_stream_delivers_to_two_clients(client):
    first, second = connect_stream(client), connect_stream(client)
    try:
        client.portal.call(hub.broadcast, "event", {"id": "evt_1"})
        expected = {"type": "event", "data": {"id": "evt_1"}}
        assert first.receive_json() == expected
        assert second.receive_json() == expected
    finally:
        second.__exit__(None, None, None)
        first.__exit__(None, None, None)


def test_stream_keeps_sending_after_one_client_leaves(client):
    remaining, leaving = connect_stream(client), connect_stream(client)
    try:
        leaving.__exit__(None, None, None)
        client.portal.call(hub.broadcast, "stats", {"real_leaks": 1})
        assert remaining.receive_json() == {"type": "stats", "data": {"real_leaks": 1}}
    finally:
        remaining.__exit__(None, None, None)
    assert not hub.has_clients()
