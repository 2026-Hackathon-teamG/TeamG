"""/ops/stream 접속자에게 실시간 메시지를 뿌림.

메시지 형식: {"type": "event" | "actor_update" | "stats" | "reset", "data": ...}
"""
import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger(__name__)

SEND_TIMEOUT = 1.0  # 초

_clients: set[WebSocket] = set()


def has_clients() -> bool:
    return bool(_clients)


async def connect(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)


def disconnect(ws: WebSocket) -> None:
    _clients.discard(ws)


async def broadcast(type_: str, data) -> None:
    if not _clients:
        return
    text = json.dumps({"type": type_, "data": data}, ensure_ascii=False, default=str)
    targets = list(_clients)
    # 워커가 기다리는 경로라 느린 접속자 하나가 처리를 막지 않게 시간을 제한함
    results = await asyncio.gather(
        *(asyncio.wait_for(ws.send_text(text), SEND_TIMEOUT) for ws in targets),
        return_exceptions=True,
    )
    dropped = [ws for ws, result in zip(targets, results) if isinstance(result, Exception)]
    for ws in dropped:
        disconnect(ws)
    # 목록에서만 빼면 접속자는 끊긴 줄 모르므로 닫아서 다시 연결하게 함
    await asyncio.gather(
        *(asyncio.wait_for(ws.close(), SEND_TIMEOUT) for ws in dropped),
        return_exceptions=True,
    )
