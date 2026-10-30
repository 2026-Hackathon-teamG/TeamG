import os

import asyncpg

from shared import Event

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
    ('endless_export', 'api',    '/api/internal/export')
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
