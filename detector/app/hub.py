"""/ops/stream 접속자에게 실시간 메시지를 뿌림.

메시지 형식: {"type": "event" | "actor_update" | "stats" | "reset", "data": ...}
"""
import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger(__name__)

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
    results = await asyncio.gather(*(ws.send_text(text) for ws in targets), return_exceptions=True)
    for ws, result in zip(targets, results):
        if isinstance(result, Exception):
            disconnect(ws)
