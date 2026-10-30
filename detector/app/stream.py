"""관제 화면으로 event, actor_update, stats 메시지를 보내는 WebSocket."""
import asyncio
import logging
from typing import Any, Literal

import anyio
from fastapi import APIRouter, WebSocket

from shared import Actor, Event

logger = logging.getLogger(__name__)

router = APIRouter()

MessageType = Literal["event", "actor_update", "stats"]


class StreamHub:
    """클라이언트마다 큐를 두어, 느리거나 끊어진 연결이 워커를 막지 않게 합니다."""

    def __init__(self, max_queue: int = 1000):
        self._max_queue = max_queue
        self._queues: set[asyncio.Queue] = set()

    @property
    def client_count(self) -> int:
        return len(self._queues)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._queues.discard(queue)

    def publish(self, message_type: MessageType, data: Any) -> None:
        message = {"type": message_type, "data": data}
        for queue in self._queues:
            if queue.full():
                logger.warning("관제 스트림 큐가 가득 차 오래된 메시지를 버립니다")
                queue.get_nowait()
            queue.put_nowait(message)

    def publish_event(self, event: Event) -> None:
        self.publish("event", event.model_dump(mode="json"))

    def publish_actor_update(self, actor: Actor) -> None:
        self.publish("actor_update", actor.model_dump(mode="json"))

    def publish_stats(self, stats: dict[str, Any]) -> None:
        self.publish("stats", stats)


hub = StreamHub()


async def _send_messages(websocket: WebSocket, queue: asyncio.Queue) -> None:
    while True:
        await websocket.send_json(await queue.get())


async def _wait_disconnect(websocket: WebSocket) -> None:
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass


@router.websocket("/ops/stream")
async def ops_stream(websocket: WebSocket) -> None:
    # accept 전에 구독해야 연결 직후 발행된 메시지를 놓치지 않습니다.
    queue = hub.subscribe()
    try:
        await websocket.accept()
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_send_messages, websocket, queue)
            await _wait_disconnect(websocket)
            tasks.cancel_scope.cancel()
    except* Exception:
        logger.warning("관제 스트림 전송에 실패해 연결을 닫습니다", exc_info=True)
    finally:
        hub.unsubscribe(queue)
