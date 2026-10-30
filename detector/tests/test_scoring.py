import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from shared import Event

from app import scoring

T0 = datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc)
IP = "203.0.113.24"


def make_event(path="/", seconds=0.0, ip=IP, **kwargs) -> Event:
    return Event(id="evt_1", ts=T0 + timedelta(seconds=seconds), ip=ip, method="GET", path=path,
                 status=200, header_hash="abc123", routed_to="bank", **kwargs)


def score_of(*events: Event) -> int:
    state = scoring.State(first_seen=T0, last_seen=T0)
    for e in events:
        scoring.apply(state, e)
    return state.score


def customers(start: int, count: int) -> list[Event]:
    return [make_event(f"/api/v1/customers?id={start + i}", seconds=i * 5.0 * (i % 2)) for i in range(count)]


@pytest.mark.parametrize("event, expected", [
    (make_event("/admin-legacy", decoy_id="admin_legacy"), 60),
    (make_event("/robots.txt", decoy_id="robots"), 0),
    (make_event("/api/internal/export?page=1", decoy_id="endless_export"), 100),
    (make_event("/api/internal/export?page=1"), 40),
    (make_event("/", internal_header=True), 20),
    (make_event("/"), 0),
])
def test_single_event_signals(event, expected):
    assert score_of(event) == expected


def test_export_after_admin_legacy_is_not_hidden_guide():
    assert score_of(make_event("/admin-legacy"), make_event("/api/internal/export?page=1")) == 0


def test_same_signal_counts_once():
    assert score_of(*[make_event("/", seconds=i * 5.0 * (i % 2), internal_header=True) for i in range(3)]) == 20


def test_sequential_ids_need_ten_in_a_row():
    assert score_of(*customers(1001, 9)) == 0
    assert score_of(*customers(1001, 10)) == 25


def test_gap_in_ids_restarts_run():
    gap = customers(1001, 5) + customers(2001, 9)
    assert score_of(*gap) == 0


def test_mechanical_interval_needs_twenty_gaps():
    regular = [make_event("/", seconds=float(i)) for i in range(21)]
    assert score_of(*regular[:20]) == 0
    assert score_of(*regular) == 15


def test_irregular_interval_is_not_mechanical():
    assert score_of(*[make_event("/", seconds=i * 5.0 * (i % 2)) for i in range(21)]) == 0


@pytest.fixture
def world(monkeypatch):
    """격리 경로의 바깥(DB, Redis, WS)을 기록만 하는 가짜로 바꿈."""
    scoring.reset()
    saved, keys, sent = [], {}, []

    class FakeRedis:
        decoys = [b"1", b"0"]
        seq = 0

        async def hvals(self, key):
            return self.decoys

        async def incr(self, key):
            self.seq += 1
            return self.seq

        async def mset(self, mapping):
            keys.update(mapping)

    async def save_actor(actor, links):
        saved.append((actor, links))

    async def broadcast(type_, data):
        sent.append((type_, data))

    redis = FakeRedis()
    monkeypatch.setattr(scoring.rds, "client", redis)
    monkeypatch.setattr(scoring.db, "save_actor", save_actor)
    monkeypatch.setattr(scoring.hub, "broadcast", broadcast)
    yield redis, saved, keys, sent
    scoring.reset()


def run(*events: Event) -> None:
    async def go():
        for e in events:
            await scoring.process(e)
    asyncio.run(go())


def attack(count: int) -> list[Event]:
    return [make_event(f"/api/v1/customers?id={1001 + i}", seconds=float(i), internal_header=True)
            for i in range(count)]


def test_below_threshold_not_quarantined(world):
    _, saved, keys, sent = world
    run(*attack(20))    # 헤더 20 + 연속 id 25. 요청 간격은 아직 19개
    assert scoring._states[IP].score == 45
    assert (saved, keys, sent) == ([], {}, [])


def test_threshold_boundary(monkeypatch, world):
    _, saved, _, _ = world
    # 실제 점수 조합으로는 59점이 나오지 않아 점수를 바꿔서 경계를 확인
    monkeypatch.setitem(scoring.SCORES, "internal_header", 59)
    monkeypatch.setitem(scoring.SCORES, "hidden_guide", 1)
    run(make_event("/", internal_header=True))
    assert saved == []
    run(make_event("/api/internal/export?page=1", seconds=1))
    assert [a.score for a, _ in saved] == [60]


def test_issue_completion_scenario_quarantines_as_a01(world):
    _, saved, keys, sent = world
    run(*attack(21))
    actor, links = saved[0]
    assert (actor.id, actor.status, actor.score) == ("A-01", "quarantined", 60)
    assert links == [("ip", IP)]
    assert keys == {f"quarantine:ip:{IP}": "A-01"}
    assert [t for t, _ in sent] == ["actor_update"]
    assert sent[0][1]["id"] == "A-01"


def test_later_session_and_token_join_quarantine(world):
    _, saved, keys, sent = world
    run(make_event("/admin-legacy", decoy_id="admin_legacy"))
    run(make_event("/", session_id="s1", token="pt_x", seconds=1))
    assert keys == {f"quarantine:ip:{IP}": "A-01", "quarantine:session:s1": "A-01", "quarantine:token:pt_x": "A-01"}
    assert len(sent) == 2
    run(make_event("/", session_id="s1", token="pt_x", seconds=2))
    assert len(sent) == 2       # 바뀐 게 없으면 다시 보내지 않음
    assert [a.id for a, _ in saved] == ["A-01"] * 3


def test_each_target_gets_next_actor_id(world):
    _, saved, _, _ = world
    run(make_event("/admin-legacy", decoy_id="admin_legacy"),
        make_event("/admin-legacy", ip="198.51.100.7", decoy_id="admin_legacy"))
    assert [a.id for a, _ in saved] == ["A-01", "A-02"]


def test_gateway_actor_id_is_reused(world):
    redis, saved, _, _ = world
    run(make_event("/admin-legacy", decoy_id="admin_legacy", actor_id="A-07"))
    assert saved[0][0].id == "A-07"
    assert redis.seq == 0


def test_decoys_off_scores_without_quarantine(world):
    redis, saved, keys, _ = world
    redis.decoys = [b"0", b"0"]
    run(*attack(21))
    assert (saved, keys) == ([], {})
    assert scoring._states[IP].score == 60


def test_decoys_off_keeps_existing_quarantine_updated(world):
    redis, saved, _, _ = world
    run(make_event("/admin-legacy", decoy_id="admin_legacy"))
    redis.decoys = [b"0", b"0"]
    run(make_event("/", internal_header=True, seconds=1))
    assert saved[-1][0].score == 80


def test_forget_clears_all_aliases(world):
    _, saved, _, _ = world
    run(make_event("/admin-legacy", decoy_id="admin_legacy"))
    scoring.forget("A-01")
    assert scoring._states == {}
    run(make_event("/"))
    assert len(saved) == 1


def test_failed_save_retries_on_next_event(monkeypatch, world):
    _, saved, keys, _ = world
    real_save = scoring.db.save_actor

    async def broken(actor, links):
        raise RuntimeError("db down")

    monkeypatch.setattr(scoring.db, "save_actor", broken)
    with pytest.raises(RuntimeError):
        run(make_event("/admin-legacy", decoy_id="admin_legacy"))
    monkeypatch.setattr(scoring.db, "save_actor", real_save)
    run(make_event("/", seconds=1))
    assert saved[0][1] == [("ip", IP)]
    assert keys == {f"quarantine:ip:{IP}": "A-01"}
