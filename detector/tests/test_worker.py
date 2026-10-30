import asyncio
from datetime import datetime, timezone

from shared import Event

from app import db, worker


def test_parse_stream_entry():
    e = Event(id="evt_1", ts=datetime.now(timezone.utc), ip="203.0.113.24", method="GET",
              path="/api/v1/customers?id=1001", status=200, header_hash="abc123",
              routed_to="bank", records_out=1)
    parsed = worker.parse({b"data": e.model_dump_json().encode()})
    assert parsed == e


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
