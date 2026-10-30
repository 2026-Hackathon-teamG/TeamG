import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from shared import Event

from app import linking, scoring

T0 = datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc)
IP_A, IP_B = "203.0.113.24", "198.51.100.7"


def token_for(actor_id="A-01", page=1) -> str:
    return f"pt_{actor_id}_{page}_{linking.sign(actor_id, page)}"


def make_event(path="/", seconds=0.0, ip=IP_A, **kwargs) -> Event:
    return Event(id="evt_1", ts=T0 + timedelta(seconds=seconds), ip=ip, method="GET", path=path,
                 status=200, header_hash="abc123", routed_to="bank", **kwargs)


def decoy_hit(**kwargs) -> Event:
    return make_event("/admin-legacy", decoy_id="admin_legacy", **kwargs)


def run(*events: Event) -> None:
    async def go():
        for e in events:
            await scoring.process(e)
    asyncio.run(go())


@pytest.fixture
def world(monkeypatch):
    """바깥(DB, Redis, WS)을 기록만 하는 가짜로 바꿈."""
    scoring.reset()
    monkeypatch.setattr(linking, "TOKEN_SECRET", "secret")
    links, keys, estimated, absorbed, sent = {}, {}, [], [], []

    class FakeRedis:
        seq = 0

        async def hvals(self, key):
            return [b"1"]

        async def incr(self, key):
            self.seq += 1
            return self.seq

        async def mset(self, mapping):
            keys.update(mapping)

    async def save_actor(actor, new_links):
        links.setdefault(actor.id, set()).update(new_links)

    async def save_estimated_link(actor_id, ip):
        estimated.append((actor_id, ip))

    async def absorb_actor(old_id, actor_id):
        absorbed.append((old_id, actor_id))
        return {"id": old_id, "status": "released", "score": 60, "first_seen": T0, "last_seen": T0}

    async def broadcast(type_, data):
        sent.append(data)

    monkeypatch.setattr(scoring.rds, "client", FakeRedis())
    monkeypatch.setattr(scoring.db, "save_actor", save_actor)
    monkeypatch.setattr(scoring.db, "save_estimated_link", save_estimated_link)
    monkeypatch.setattr(scoring.db, "absorb_actor", absorb_actor)
    monkeypatch.setattr(scoring.hub, "broadcast", broadcast)
    yield links, keys, estimated, absorbed, sent
    scoring.reset()


def test_verify_accepts_only_correct_signature(monkeypatch):
    monkeypatch.setattr(linking, "TOKEN_SECRET", "secret")
    good = token_for()
    assert linking.verify(good) == "A-01"
    assert linking.verify(good[:-1] + ("0" if good[-1] != "0" else "1")) is None      # 서명 변조
    assert linking.verify(good.replace("A-01", "A-02")) is None                       # 다른 공격 주체로 변조
    assert linking.verify(good.replace("_1_", "_2_")) is None                         # 페이지 변조


@pytest.mark.parametrize("token", [None, "", "pt_x", "abc", "pt_A-01_1_zz", "pt_A-01_x_" + "0" * 64])
def test_verify_rejects_bad_format(monkeypatch, token):
    monkeypatch.setattr(linking, "TOKEN_SECRET", "secret")
    assert linking.verify(token) is None


def test_verify_rejects_everything_without_secret(monkeypatch):
    monkeypatch.setattr(linking, "TOKEN_SECRET", "secret")
    token = token_for()
    monkeypatch.setattr(linking, "TOKEN_SECRET", "")
    assert linking.verify(token) is None


def test_similarity_boundary_at_point_seven():
    paths = [f"/p{i}" for i in range(12)]   # 3-gram 10개
    assert linking.similar(paths, paths[:9])        # 공통 7개 / 합집합 10개 = 0.7
    assert not linking.similar(paths, paths[:8])    # 공통 6개 / 합집합 10개 = 0.6


def test_similarity_needs_at_least_one_three_gram():
    assert not linking.similar(["/a", "/b"], ["/a", "/b"])


def test_token_from_other_ip_merges_into_actor(world):
    links, keys, _, _, sent = world
    run(decoy_hit())
    run(make_event("/api/v1/customers", ip=IP_B, seconds=1, token=token_for()))
    assert links["A-01"] == {("ip", IP_A), ("ip", IP_B), ("token", token_for())}
    assert keys[f"quarantine:ip:{IP_B}"] == "A-01"
    assert scoring._states[IP_A] is scoring._states[IP_B] is scoring._states["A-01"]
    assert sent[-1]["id"] == "A-01"


def test_forged_token_does_not_merge_or_quarantine(world):
    links, keys, _, _, _ = world
    run(decoy_hit())
    forged = token_for()[:-1] + ("0" if token_for()[-1] != "0" else "1")
    run(make_event("/api/v1/customers", ip=IP_B, seconds=1, token=forged))
    assert links["A-01"] == {("ip", IP_A)}
    assert f"quarantine:ip:{IP_B}" not in keys
    assert scoring._states[IP_B].actor_id is None


def test_merge_counts_shared_signal_once_and_combines_scores(world):
    links, _, _, _, _ = world
    run(decoy_hit(internal_header=True))                                    # 60 + 20
    run(make_event("/", ip=IP_B, seconds=1, internal_header=True))          # 20
    run(make_event("/api/internal/export?page=2", ip=IP_B, seconds=2))      # 20 + 40
    assert scoring._states[IP_B].score == 60
    run(make_event("/", ip=IP_B, seconds=3, token=token_for()))
    assert scoring._states["A-01"].score == 120                             # 60 + 20 + 40


def test_merging_two_actors_absorbs_the_old_one(world):
    links, keys, _, absorbed, sent = world
    run(decoy_hit(), decoy_hit(ip=IP_B, seconds=1))
    assert keys[f"quarantine:ip:{IP_B}"] == "A-02"
    run(make_event("/", ip=IP_B, seconds=2, token=token_for()))
    assert absorbed == [("A-02", "A-01")]
    assert keys[f"quarantine:ip:{IP_B}"] == "A-01"
    assert ("ip", IP_B) in links["A-01"]
    assert {"A-01", "A-02"} <= {m["id"] for m in sent}
    assert scoring._states["A-02"] is scoring._states["A-01"]


def test_similar_behavior_is_marked_estimated_without_quarantine(world):
    links, keys, estimated, _, sent = world
    route = ["/robots.txt", "/api/v1/docs", "/api/v1/customers"]
    run(*[make_event(p, seconds=i, ua="agent") for i, p in enumerate(route)], decoy_hit(seconds=4, ua="agent"))
    assert links["A-01"] == {("ip", IP_A)}
    run(*[make_event(p, ip=IP_B, seconds=10 + i, ua="agent") for i, p in enumerate(route)])
    run(make_event("/admin-legacy", ip=IP_B, seconds=14, ua="agent"))
    assert estimated == [("A-01", IP_B)]
    assert f"quarantine:ip:{IP_B}" not in keys
    assert ("ip", IP_B) not in links["A-01"]
    assert scoring._states[IP_B].actor_id is None
    updates = len(sent)
    run(make_event("/admin-legacy", ip=IP_B, seconds=15, ua="agent"))
    assert (len(estimated), len(sent)) == (1, updates)      # 한 번만 표시


def test_different_fingerprint_is_not_estimated(world):
    _, _, estimated, _, _ = world
    route = ["/robots.txt", "/api/v1/docs", "/api/v1/customers", "/admin-legacy"]
    run(*[make_event(p, seconds=i, ua="agent") for i, p in enumerate(route[:-1])], decoy_hit(seconds=4, ua="agent"))
    run(*[make_event(p, ip=IP_B, seconds=10 + i, ua="browser") for i, p in enumerate(route)])
    assert estimated == []
