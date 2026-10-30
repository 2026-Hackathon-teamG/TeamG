import asyncio
import logging
import os
from urllib.parse import parse_qs, urlsplit

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from shared import Event, tokens

from . import db, defense, hub, mfa_defense, scoring

log = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
TOKEN_SECRET = os.environ.get("TOKEN_SECRET", "change-me")
STREAM = "events"
GROUP = "detector"
CONSUMER = os.environ.get("HOSTNAME", "detector-1")


def parse(fields: dict[bytes, bytes]) -> Event:
    return Event.model_validate_json(fields[b"data"])


def issued_canaries(events: list[Event]) -> list[tuple]:
    """endless_export 응답마다 gateway가 내준 next_token을 같은 규칙으로 다시 계산해 기록."""
    rows = []
    for e in events:
        if e.decoy_id != "endless_export" or e.status != 200 or not e.actor_id:
            continue
        query_page = (parse_qs(urlsplit(e.path).query).get("page") or [None])[0]
        page = tokens.export_page(query_page, e.token, TOKEN_SECRET)
        rows.append((tokens.sign(e.actor_id, page + 1, TOKEN_SECRET), e.actor_id, page + 1, e.ip, e.ts))
    return rows


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
        if canaries := issued_canaries(events):
            await db.insert_canaries(canaries)
        for e in events:
            await hub.broadcast("event", e.model_dump(mode="json"))
            try:
                await scoring.process(e)
            except Exception:
                # 이벤트 저장과 전송은 계속되게 함. 격리는 다음 이벤트에서 다시 시도됨
                log.exception("scoring failed: %s", e.id)
            try:
                await defense.process(e)
            except Exception:
                log.exception("defense failed: %s", e.id)
            try:
                await mfa_defense.process(e)
            except Exception:
                log.exception("mfa_defense failed: %s", e.id)
        if hub.has_clients():
            await hub.broadcast("stats", await db.stats())
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
            except ResponseError as e:
                # 누가 스트림을 지웠으면 group을 다시 만듦
                if "NOGROUP" in str(e):
                    await ensure_group(r)
                    continue
                log.exception("worker loop error")
                await asyncio.sleep(1)
            except Exception:
                log.exception("worker loop error")
                await asyncio.sleep(1)
    finally:
        await r.aclose()