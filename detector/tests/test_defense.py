import asyncio
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest

from shared import Event

from app import defense, rds


def fail_event(ip: str, ts: datetime) -> Event:
    return Event(id="evt", ts=ts, ip=ip, method="POST", path="/api/v1/login", status=401,
                 header_hash="aaaaaa", routed_to="bank", login_result="fail", account="admin")


@pytest.fixture
def fake_rds(monkeypatch):
    monkeypatch.setattr(rds, "client", fakeredis.aioredis.FakeRedis())
    defense.reset()
    sent = []
    monkeypatch.setattr(defense.hub, "broadcast", lambda t, d: sent.append((t, d)) or _noop())
    return sent


async def _noop():
    return None


def test_blocks_ip_after_threshold_fails(fake_rds):
    async def scenario():
        t0 = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        # 5회째에서 차단 (THRESHOLD=5)
        for i in range(defense.THRESHOLD):
            await defense.process(fail_event("203.0.113.24", t0 + timedelta(seconds=i)))
        assert await rds.client.exists(rds.block_key("ip", "203.0.113.24"))
        ttl = await rds.client.ttl(rds.block_key("ip", "203.0.113.24"))
        assert 0 < ttl <= defense.BLOCK_SECONDS
        assert [d["value"] for t, d in fake_rds if t == "block"] == ["203.0.113.24"]  # 한 번만 방송

    asyncio.run(scenario())


def test_old_fails_fall_out_of_window(fake_rds):
    async def scenario():
        t0 = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        # WINDOW보다 넓게 흩뿌리면 임계치에 닿지 않음
        for i in range(defense.THRESHOLD + 2):
            await defense.process(fail_event("198.51.100.7", t0 + timedelta(seconds=i * 20)))
        assert not await rds.client.exists(rds.block_key("ip", "198.51.100.7"))

    asyncio.run(scenario())


def test_success_and_other_ips_do_not_count(fake_rds):
    async def scenario():
        t0 = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        for i in range(defense.THRESHOLD):
            e = fail_event("192.0.2.55", t0 + timedelta(seconds=i))
            e.login_result = "success"   # 성공은 세지 않음
            await defense.process(e)
        assert not await rds.client.exists(rds.block_key("ip", "192.0.2.55"))

    asyncio.run(scenario())


def fail_fp(ip: str, ts: datetime, header_hash: str = "aaaaaa", ua: str | None = None) -> Event:
    return Event(id="evt", ts=ts, ip=ip, method="POST", path="/api/v1/login", status=401,
                 header_hash=header_hash, ua=ua, routed_to="bank", login_result="fail", account="admin")


def test_r2_rotating_ip_same_fingerprint_blocks_all(fake_rds):
    async def scenario():
        t0 = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        # IP를 바꿔 가며 2+2+1회(합 5) 실패. 어느 IP도 혼자서는 THRESHOLD 미만
        plan = [("203.0.113.24", 2), ("198.51.100.7", 2), ("192.0.2.55", 1)]
        i = 0
        for ip, n in plan:
            for _ in range(n):
                await defense.process(fail_fp(ip, t0 + timedelta(seconds=i)))
                i += 1
        for ip, _ in plan:
            assert await rds.client.exists(rds.block_key("ip", ip)), ip
        assert "R2" in {d["rule"] for t, d in fake_rds if t == "block"}

    asyncio.run(scenario())


def test_r2_different_fingerprints_not_grouped(fake_rds):
    async def scenario():
        t0 = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        # 지문이 다르면 합산되지 않아 아무도 차단되지 않음
        await defense.process(fail_fp("203.0.113.24", t0, header_hash="aaaaaa"))
        await defense.process(fail_fp("203.0.113.24", t0 + timedelta(seconds=1), header_hash="aaaaaa"))
        await defense.process(fail_fp("198.51.100.7", t0 + timedelta(seconds=2), header_hash="bbbbbb"))
        await defense.process(fail_fp("198.51.100.7", t0 + timedelta(seconds=3), header_hash="bbbbbb"))
        assert not await rds.client.exists(rds.block_key("ip", "203.0.113.24"))
        assert not await rds.client.exists(rds.block_key("ip", "198.51.100.7"))

    asyncio.run(scenario())
