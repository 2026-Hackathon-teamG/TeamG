import os
from datetime import datetime
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from shared import Actor
from shared.models import DecoyId

from . import db, hub, rds, scoring

AGENT_URL = os.environ.get("AGENT_URL", "http://agent:8004")

router = APIRouter(prefix="/ops")


class Toggle(BaseModel):
    enabled: bool


class RunRequest(BaseModel):
    mode: Literal["live", "replay"] = "live"
    run_file: str | None = None


async def sync_decoys_to_redis(decoys: list[dict]) -> None:
    """gateway는 Redis만 보므로 DB 값을 그대로 옮김."""
    if decoys:
        await rds.client.hset(rds.DECOYS_KEY, mapping={d["id"]: "1" if d["enabled"] else "0" for d in decoys})


async def push_stats() -> None:
    if hub.has_clients():
        await hub.broadcast("stats", await db.stats())


@router.websocket("/stream")
async def stream(ws: WebSocket):
    await hub.connect(ws)
    try:
        await ws.send_json({"type": "stats", "data": await db.stats()})
        while True:
            await ws.receive_text()   # 클라이언트 메시지는 쓰지 않음. 연결 유지용
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)


@router.get("/events")
async def events(since: datetime | None = None, limit: int = Query(100, ge=1, le=1000)):
    return await db.list_events(since, limit)


@router.get("/actors")
async def actors():
    return await db.list_actors()


@router.get("/actors/{actor_id}")
async def actor(actor_id: str):
    found = await db.get_actor(actor_id)
    if found is None:
        raise HTTPException(404, "actor not found")
    return found


@router.post("/actors/{actor_id}/release")
async def release(actor_id: str):
    # 해제 도중 들어온 요청이 남은 점수로 상태를 quarantined로 되돌리지 않게 점수부터 지움
    scoring.forget(actor_id)
    targets = await db.release_actor(actor_id)
    if targets is None:
        raise HTTPException(404, "actor not found")
    if targets:
        await rds.client.delete(*(rds.quarantine_key(k, v) for k, v in targets))
    released =Actor.model_validate(await db.get_actor(actor_id))
    await hub.broadcast("actor_update", released.model_dump(mode="json"))
    return {"id": actor_id, "status": "released", "released_keys": len(targets)}


@router.get("/decoys")
async def decoys():
    return await db.list_decoys()


@router.put("/decoys")
async def set_all_decoys(body: Toggle):
    updated = await db.set_decoys(body.enabled)
    await sync_decoys_to_redis(updated)
    return updated


@router.put("/decoys/{decoy_id}")
async def set_decoy(decoy_id: DecoyId, body: Toggle):
    updated = await db.set_decoys(body.enabled, decoy_id)
    await sync_decoys_to_redis(updated)
    return updated[0]


@router.get("/stats")
async def stats():
    return await db.stats()


@router.post("/demo/reset")
async def demo_reset():
    await db.reset()
    # 스트림은 지우지 않고 비워야 consumer group이 유지됨
    await rds.client.xtrim(rds.STREAM, maxlen=0, approximate=False)
    keys = [k async for k in rds.client.scan_iter(match=rds.QUARANTINE_PREFIX + "*", count=500)]
    if keys:
        await rds.client.delete(*keys)
    await rds.client.delete(rds.ACTOR_SEQ_KEY)
    scoring.reset()
    await hub.broadcast("reset", None)
    await push_stats()
    return {"ok": True, "quarantine_keys_cleared": len(keys)}


@router.post("/demo/run")
async def demo_run(body: RunRequest):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{AGENT_URL}/run", json=body.model_dump(exclude_none=True))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"agent unreachable: {e.__class__.__name__}")
    if resp.status_code >= 400:
        raise HTTPException(502, f"agent returned {resp.status_code}")
    return resp.json()
