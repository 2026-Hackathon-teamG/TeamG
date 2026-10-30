import asyncio
import logging
import os

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from shared import Event

from . import db, stream

log = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
STREAM = "events"
GROUP = "detector"
CONSUMER = os.environ.get("HOSTNAME", "detector-1")


def parse(fields: dict[bytes, bytes]) -> Event:
    return Event.model_validate_json(fields[b"data"])


async def ensure_group(r: aioredis.Redis) -> None:
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def handle(r: aioredis.Redis, entries: list) -> None:
    ids, events = [], []
    for msg_id, fields in entries:
        ids.append(msg_id)
        try:
            events.append(parse(fields))
        except Exception:
            log.exception("bad event %s, skipped", msg_id)
    if events:
        await db.insert_events(events)
        for event in events:
            stream.hub.publish_event(event)
    # 다음 단계(점수, 묶음)는 여기서 events를 넘겨받아 처리
    if ids:
        await r.xack(STREAM, GROUP, *ids)


async def run() -> None:
    r = aioredis.from_url(REDIS_URL)
    await ensure_group(r)
    # 재시작 시 ack 못 한 메시지부터 처리
    last_id = "0"
    try:
        while True:
            try:
                resp = await r.xreadgroup(GROUP, CONSUMER, {STREAM: last_id}, count=100, block=1000)
                entries = resp[0][1] if resp else []
                if last_id == "0" and not entries:
                    last_id = ">"
                    continue
                await handle(r, entries)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("worker loop error")
                await asyncio.sleep(1)
    finally:
        await r.aclose()
