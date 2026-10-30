import asyncio
from datetime import datetime, timezone

from shared import Event, tokens

from app import db, worker


def test_parse_stream_entry():
    e = Event(id="evt_1", ts=datetime.now(timezone.utc), ip="203.0.113.24", method="GET",
              path="/api/v1/customers?id=1001", status=200, header_hash="abc123",
              routed_to="bank", records_out=1)
    parsed = worker.parse({b"data": e.model_dump_json().encode()})
    assert parsed == e


def export_event(path, token=None, actor_id="A-01", ip="203.0.113.24"):
    return Event(id="evt_x", ts=datetime.now(timezone.utc), ip=ip, method="GET", path=path, status=200,
                 header_hash="abc123", decoy_id="endless_export", token=token, actor_id=actor_id,
                 routed_to="decoy", records_out=50)


def test_issued_canaries_match_gateway_next_token():
    secret = worker.TOKEN_SECRET
    page2 = tokens.sign("A-01", 2, secret)
    rows = worker.issued_canaries([
        export_event("/api/internal/export?page=1"),
        export_event(f"/api/internal/export?token={page2}", token=page2, ip="198.51.100.7"),
        export_event("/admin-legacy", actor_id=None),
    ])
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        (page2, "A-01", 2, "203.0.113.24"),
        (tokens.sign("A-01", 3, secret), "A-01", 3, "198.51.100.7"),
    ]


def test_insert_covers_all_event_fields():
    assert db._EVENT_COLS == list(Event.model_fields)
    assert f"${len(Event.model_fields)})" in db._INSERT_EVENT


def test_ip_count_only_counts_confirmed_ips(monkeypatch):
    queries = []

    class FakePool:
        async def fetch(self, query):
            queries.append(query)
            return []

    monkeypatch.setattr(db, "pool", FakePool())
    asyncio.run(db.list_actors())
    assert "l.confidence = '확정'" in queries[0]
