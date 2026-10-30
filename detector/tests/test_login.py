import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from shared import Event

from app import scoring

T0 = datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc)
LOGIN = "/api/v1/login"


def fail(ip, seconds, ua="agent/1", header_hash="abc123") -> Event:
    return Event(id=f"evt_{ip}_{seconds}", ts=T0 + timedelta(seconds=seconds), ip=ip, method="POST",
                 path=LOGIN, status=401, header_hash=header_hash, ua=ua, routed_to="bank")


@pytest.fixture
def world(monkeypatch):
    scoring.reset()
    saved, keys = [], {}

    class FakeRedis:
        seq = 0
        decoys_off = False      # 로그인 잠금은 미끼 on/off와 무관해야 함

        async def hvals(self, key):
            return [b"0", b"0"] if self.decoys_off else [b"1"]

        async def incr(self, key):
            self.seq += 1
            return self.seq

        async def mset(self, mapping):
            keys.update(mapping)

    async def save_actor(actor, links):
        saved.append((actor, sorted(links)))

    async def noop(*a, **k):
        pass

    redis = FakeRedis()
    monkeypatch.setattr(scoring.rds, "client", redis)
    monkeypatch.setattr(scoring.db, "save_actor", save_actor)
    monkeypatch.setattr(scoring.hub, "broadcast", noop)
    yield redis, saved, keys
    scoring.reset()


def run(*events: Event) -> None:
    async def go():
        for e in events:
            await scoring.process(e)
    asyncio.run(go())


def test_four_fails_one_ip_not_locked(world):
    _, saved, keys = world
    run(*[fail("203.0.113.24", i) for i in range(4)])
    assert (saved, keys) == ([], {})


def test_five_fails_one_ip_locks_r1(world):
    _, saved, keys = world
    run(*[fail("203.0.113.24", i) for i in range(5)])
    assert [a.id for a, _ in saved] == ["A-01"]
    assert keys == {"quarantine:ip:203.0.113.24": "A-01"}


def test_fails_outside_window_do_not_count(world):
    _, saved, _ = world
    # 4회 → 70초 지나 1회: 창(60초)을 벗어나 누적 안 됨
    run(*[fail("203.0.113.24", i) for i in range(4)], fail("203.0.113.24", 70))
    assert saved == []


def test_rotating_ip_same_fingerprint_locks_as_one_subject_r2(world):
    _, saved, keys = world
    # IP를 매번 바꾸며 1~2회씩 실패해도 같은 지문이면 한 주체로 합산되어 잠김
    run(fail("203.0.113.24", 0), fail("203.0.113.24", 1),
        fail("198.51.100.7", 2), fail("198.51.100.7", 3),
        fail("192.0.2.55", 4))
    assert [a.id for a, _ in saved] == ["A-01"]
    assert set(keys) == {
        "quarantine:ip:203.0.113.24", "quarantine:ip:198.51.100.7", "quarantine:ip:192.0.2.55",
    }
    assert set(keys.values()) == {"A-01"}


def test_different_fingerprint_not_grouped(world):
    _, saved, _ = world
    # 서로 다른 지문의 IP들이 1~2회씩 실패 → 합산되지 않아 아무도 안 잠김
    run(fail("203.0.113.24", 0, ua="chrome"), fail("203.0.113.24", 1, ua="chrome"),
        fail("198.51.100.7", 2, ua="firefox"), fail("198.51.100.7", 3, ua="firefox"))
    assert saved == []


def test_lock_fires_even_when_decoys_off(world):
    redis, saved, _ = world
    redis.decoys_off = True
    run(*[fail("203.0.113.24", i) for i in range(5)])
    assert [a.id for a, _ in saved] == ["A-01"]
