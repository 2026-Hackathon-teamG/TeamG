import hashlib
import logging
import os
from collections.abc import Mapping
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import Request
from ulid import ULID

from shared import Event

log = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
STREAM = "events"
STREAM_MAXLEN = 100_000

_redis: aioredis.Redis | None = None


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE") == "1"


def header_hash(names: list[str]) -> str:
    """헤더 이름 순서의 sha1 앞 6자리. 값은 보지 않음."""
    joined = ",".join(n.lower() for n in names)
    return hashlib.sha1(joined.encode()).hexdigest()[:6]


def client_ip(headers: Mapping[str, str], peer: str | None) -> str:
    if demo_mode() and headers.get("x-sim-ip"):
        return headers["x-sim-ip"]
    return peer or "unknown"


def agent_note(headers: Mapping[str, str]) -> str | None:
    if not demo_mode() or not headers.get("x-agent-note"):
        return None
    # starlette는 헤더를 latin-1로 풀기 때문에 UTF-8 한글을 되살림
    raw = headers["x-agent-note"]
    try:
        return raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def build(
    request: Request,
    status: int,
    *,
    routed_to: str = "bank",
    decoy_id: str | None = None,
    actor_id: str | None = None,
    records_out: int = 0,
    login_result: str | None = None,
    account: str | None = None,
) -> Event:
    path = request.url.path
    if request.url.query:
        path += "?" + request.url.query
    return Event(
        id=f"evt_{ULID()}",
        ts=datetime.now(timezone.utc),
        ip=client_ip(request.headers, request.client.host if request.client else None),
        method=request.method,
        path=path,
        status=status,
        session_id=request.cookies.get("sessionid"),
        ua=request.headers.get("user-agent"),
        header_hash=header_hash([k.decode() for k, _ in request.headers.raw]),
        decoy_id=decoy_id,
        token=request.query_params.get("token"),
        actor_id=actor_id,
        routed_to=routed_to,
        records_out=records_out,
        agent_note=agent_note(request.headers),
        internal_header="x-internal-request" in request.headers,
        login_result=login_result,
        account=account,
    )


async def startup() -> None:
    global _redis
    _redis = aioredis.from_url(REDIS_URL)


async def shutdown() -> None:
    if _redis:
        await _redis.aclose()


def redis() -> aioredis.Redis:
    return _redis


async def publish(event: Event) -> None:
    """응답을 보낸 뒤 BackgroundTask로 호출. Redis 장애가 프록시를 막지 않게 예외는 로그만."""
    try:
        await _redis.xadd(STREAM, {"data": event.model_dump_json()},
                          maxlen=STREAM_MAXLEN, approximate=True)
    except Exception:
        log.exception("event publish failed: %s", event.id)
