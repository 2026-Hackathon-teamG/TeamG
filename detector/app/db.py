import os
from datetime import datetime

import asyncpg

from shared import Actor, Event

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://mikki:mikki@postgres:5432/mikki")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL,
    ip          TEXT NOT NULL,
    method      TEXT NOT NULL,
    path        TEXT NOT NULL,
    status      INT NOT NULL,
    session_id  TEXT,
    ua          TEXT,
    header_hash TEXT NOT NULL,
    decoy_id    TEXT,
    token       TEXT,
    actor_id    TEXT,
    routed_to   TEXT NOT NULL,
    records_out INT NOT NULL DEFAULT 0,
    agent_note  TEXT
);
ALTER TABLE events ADD COLUMN IF NOT EXISTS internal_header BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE events ADD COLUMN IF NOT EXISTS login_result TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS account TEXT;
CREATE INDEX IF NOT EXISTS events_ts_idx ON events (ts);
CREATE INDEX IF NOT EXISTS events_ip_idx ON events (ip);

CREATE TABLE IF NOT EXISTS actors (
    id         TEXT PRIMARY KEY,
    status     TEXT NOT NULL,
    score      INT NOT NULL DEFAULT 0,
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS actor_links (
    actor_id   TEXT NOT NULL REFERENCES actors (id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    value      TEXT NOT NULL,
    confidence TEXT NOT NULL,
    PRIMARY KEY (actor_id, kind, value)
);

CREATE TABLE IF NOT EXISTS decoys (
    id      TEXT PRIMARY KEY,
    kind    TEXT NOT NULL,
    path    TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);
INSERT INTO decoys (id, kind, path) VALUES
    ('robots',         'inject', '/robots.txt'),
    ('admin_legacy',   'page',   '/admin-legacy'),
    ('docs_bait',      'inject', '/api/v1/docs'),
    ('endless_export', 'api',    '/api/internal/export'),
    ('audit',          'api',    '/internal/v2/audit/001')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS canary_tokens (
    token     TEXT PRIMARY KEY,
    actor_id  TEXT NOT NULL,
    page      INT NOT NULL,
    ip        TEXT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL
);
"""

_EVENT_COLS = list(Event.model_fields)
_INSERT_EVENT = (
    f"INSERT INTO events ({', '.join(_EVENT_COLS)}) "
    f"VALUES ({', '.join(f'${i}' for i in range(1, len(_EVENT_COLS) + 1))}) "
    "ON CONFLICT (id) DO NOTHING"
)

pool: asyncpg.Pool | None = None


async def startup() -> None:
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)


async def shutdown() -> None:
    if pool:
        await pool.close()


async def insert_events(events: list[Event]) -> None:
    rows = [tuple(getattr(e, c) for c in _EVENT_COLS) for e in events]
    async with pool.acquire() as conn:
        await conn.executemany(_INSERT_EVENT, rows)


async def save_actor(actor: Actor, links: list[tuple[str, str]]) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO actors (id, status, score, first_seen, last_seen) VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, "
            "score = GREATEST(actors.score, EXCLUDED.score), last_seen = EXCLUDED.last_seen",
            actor.id, actor.status, actor.score, actor.first_seen, actor.last_seen,
        )
        # 추정으로 표시됐던 값이 토큰으로 확인되면 확정으로 올림
        await conn.executemany(
            "INSERT INTO actor_links (actor_id, kind, value, confidence) VALUES ($1, $2, $3, '확정') "
            "ON CONFLICT (actor_id, kind, value) DO UPDATE SET confidence = '확정'",
            [(actor.id, kind, value) for kind, value in links],
        )


async def save_estimated_link(actor_id: str, ip: str) -> None:
    await pool.execute(
        "INSERT INTO actor_links (actor_id, kind, value, confidence) VALUES ($1, 'ip', $2, '추정') "
        "ON CONFLICT DO NOTHING",
        actor_id, ip,
    )


async def absorb_actor(old_id: str, actor_id: str) -> dict | None:
    """병합된 공격 주체를 비움. 링크는 병합 대상에 이미 저장되어 있음. 번호가 재사용되지 않게 행은 released로 남김."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM actor_links WHERE actor_id = $1", old_id)
        await conn.execute("UPDATE events SET actor_id = $2 WHERE actor_id = $1", old_id, actor_id)
        row = await conn.fetchrow("UPDATE actors SET status = 'released' WHERE id = $1 RETURNING *", old_id)
    return dict(row) if row else None


# ---------- 관제 API 조회 ----------

async def list_events(since: datetime | None, limit: int) -> list[dict]:
    # 최신 limit개를 시간순으로
    rows = await pool.fetch(
        "SELECT * FROM (SELECT * FROM events WHERE ($1::timestamptz IS NULL OR ts > $1) "
        "ORDER BY ts DESC LIMIT $2) t ORDER BY ts",
        since, limit,
    )
    return [dict(r) for r in rows]


async def list_actors() -> list[dict]:
    rows = await pool.fetch(
        "SELECT a.*, "
        "  (SELECT count(*) FROM actor_links l WHERE l.actor_id = a.id AND l.kind = 'ip' "
        "   AND l.confidence = '확정') AS ip_count "
        "FROM actors a ORDER BY a.id"
    )
    return [dict(r) for r in rows]


async def get_actor(actor_id: str) -> dict | None:
    actor = await pool.fetchrow("SELECT * FROM actors WHERE id = $1", actor_id)
    if actor is None:
        return None
    links = await pool.fetch(
        "SELECT kind, value, confidence FROM actor_links WHERE actor_id = $1 ORDER BY kind, value",
        actor_id,
    )
    # 묶이기 전 IP로 들어온 요청까지 타임라인에 포함
    timeline = await pool.fetch(
        "SELECT * FROM events WHERE actor_id = $1 "
        "OR ip IN (SELECT value FROM actor_links WHERE actor_id = $1 AND kind = 'ip') "
        "ORDER BY ts",
        actor_id,
    )
    return {**dict(actor), "links": [dict(r) for r in links], "timeline": [dict(r) for r in timeline]}


async def release_actor(actor_id: str) -> list[tuple[str, str]] | None:
    """상태를 released로 바꾸고 풀어야 할 격리 대상 (kind, value)를 돌려줌."""
    async with pool.acquire() as conn, conn.transaction():
        updated = await conn.execute("UPDATE actors SET status = 'released' WHERE id = $1", actor_id)
        if updated.endswith(" 0"):
            return None
        links = await conn.fetch(
            "SELECT kind, value FROM actor_links WHERE actor_id = $1 AND kind IN ('ip', 'session', 'token') "
            "AND confidence = '확정'",
            actor_id,
        )
    return [(r["kind"], r["value"]) for r in links]


async def list_decoys() -> list[dict]:
    rows = await pool.fetch("SELECT * FROM decoys ORDER BY id")
    return [dict(r) for r in rows]


async def set_decoys(enabled: bool, decoy_id: str | None = None) -> list[dict]:
    rows = await pool.fetch(
        "UPDATE decoys SET enabled = $1 WHERE ($2::text IS NULL OR id = $2) RETURNING *",
        enabled, decoy_id,
    )
    return [dict(r) for r in rows]


async def stats() -> dict:
    row = await pool.fetchrow(
        """
        SELECT
          COALESCE(SUM(records_out) FILTER (WHERE routed_to = 'bank'), 0)               AS real_leaks,
          COALESCE(SUM(records_out) FILTER (WHERE routed_to = 'decoy'), 0)              AS fake_records,
          COUNT(*) FILTER (WHERE decoy_id IN ('admin_legacy', 'endless_export', 'audit'))       AS trap_hits,
          COUNT(*)                                                                      AS total_events
        FROM events
        """
    )
    # 묶어 둔 시간: 공격 주체별 미끼 응답 첫 요청~마지막 요청 길이의 합
    held = await pool.fetchval(
        "SELECT COALESCE(SUM(EXTRACT(EPOCH FROM span)), 0) FROM ("
        "  SELECT MAX(ts) - MIN(ts) AS span FROM events "
        "  WHERE routed_to = 'decoy' AND actor_id IS NOT NULL GROUP BY actor_id"
        ") t"
    )
    actors = await pool.fetchval("SELECT COUNT(*) FROM actors WHERE status = 'quarantined'")
    return {**dict(row), "held_seconds": round(float(held), 1), "quarantined_actors": actors}


async def reset() -> None:
    await pool.execute("TRUNCATE events, actor_links, actors, canary_tokens")


async def insert_canaries(rows: list[tuple[str, str, int, str, datetime]]) -> None:
    """(token, actor_id, page, ip, issued_at)"""
    async with pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO canary_tokens (token, actor_id, page, ip, issued_at) "
            "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (token) DO NOTHING",
            rows,
        )
