import asyncio
import time
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared import Actor, Event

from app.main import app as detector_app
from app.stream import StreamHub, hub, ops_stream, router

NOW = datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc)

# detector 앱은 시작할 때 PostgreSQL에 연결하므로 라우터만 띄웁니다.
app = FastAPI()
app.include_router(router)


def make_event() -> Event:
    return Event(
        id="evt_01",
        ts=NOW,
        ip="203.0.113.24",
        method="GET",
        path="/api/v1/customers?id=1001",
        status=200,
        header_hash="abc123",
        routed_to="bank",
    )


def wait_for_client_count(client: TestClient, expected: int) -> None:
    deadline = time.monotonic() + 2
    while hub.client_count != expected:
        assert time.monotonic() < deadline, f"연결 수 {hub.client_count}, 기대값 {expected}"
        client.portal.call(asyncio.sleep, 0.01)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_detector_앱에_스트림_경로가_연결되어_있다():
    with TestClient(detector_app).websocket_connect("/ops/stream"):
        pass


def test_두_클라이언트가_같은_메시지를_받는다(client):
    with client.websocket_connect("/ops/stream") as first:
        with client.websocket_connect("/ops/stream") as second:
            client.portal.call(hub.publish_stats, {"real_leaks": 3})

            expected = {"type": "stats", "data": {"real_leaks": 3}}
            assert first.receive_json() == expected
            assert second.receive_json() == expected


def test_event와_actor_update를_JSON으로_보낸다(client):
    actor = Actor(id="A-01", status="quarantined", score=60, first_seen=NOW, last_seen=NOW)

    with client.websocket_connect("/ops/stream") as websocket:
        client.portal.call(hub.publish_event, make_event())
        client.portal.call(hub.publish_actor_update, actor)

        event_message = websocket.receive_json()
        assert event_message["type"] == "event"
        assert event_message["data"]["id"] == "evt_01"
        assert event_message["data"]["ts"] == "2026-10-31T05:00:00Z"

        actor_message = websocket.receive_json()
        assert actor_message["type"] == "actor_update"
        assert actor_message["data"]["id"] == "A-01"
        assert actor_message["data"]["status"] == "quarantined"


def test_한_연결이_끊겨도_다른_연결로_계속_보낸다(client):
    with client.websocket_connect("/ops/stream") as remaining:
        with client.websocket_connect("/ops/stream"):
            wait_for_client_count(client, 2)
        wait_for_client_count(client, 1)

        client.portal.call(hub.publish_stats, {"real_leaks": 1})

        assert remaining.receive_json() == {"type": "stats", "data": {"real_leaks": 1}}

    wait_for_client_count(client, 0)


def test_큐가_가득_차도_막히지_않고_오래된_메시지를_버린다():
    async def scenario():
        stream_hub = StreamHub(max_queue=2)
        queue = stream_hub.subscribe()

        for value in (1, 2, 3):
            stream_hub.publish_stats({"value": value})

        return [queue.get_nowait()["data"]["value"] for _ in range(queue.qsize())]

    assert asyncio.run(scenario()) == [2, 3]


def test_전송에_실패하면_구독을_해제한다():
    class BrokenWebSocket:
        async def accept(self):
            pass

        async def send_json(self, message):
            raise RuntimeError("연결이 끊어졌습니다")

        async def receive(self):
            await asyncio.Event().wait()

    async def scenario():
        task = asyncio.create_task(ops_stream(BrokenWebSocket()))
        while hub.client_count == 0:
            await asyncio.sleep(0)
        hub.publish_stats({"real_leaks": 1})
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())

    assert hub.client_count == 0
