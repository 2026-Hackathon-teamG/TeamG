"""이벤트를 채점하고 60점 이상이면 격리함."""
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from shared import Actor, Event

from . import db, hub, rds

THRESHOLD = 60
SCORES = {"decoy": 60, "hidden_guide": 40, "internal_header": 20, "sequential_ids": 25, "mechanical": 15}
SEQUENTIAL_RUN = 10
INTERVALS = 20
MAX_STDEV = 0.2


@dataclass
class State:
    first_seen: datetime
    last_seen: datetime
    score: int = 0
    signals: set[str] = field(default_factory=set)
    visited_admin: bool = False
    id_runs: dict[str, tuple[int, int]] = field(default_factory=dict)   # 경로별 (마지막 id, 연속 횟수)
    times: deque[datetime] = field(default_factory=lambda: deque(maxlen=INTERVALS + 1))
    links: set[tuple[str, str]] = field(default_factory=set)
    actor_id: str | None = None
    quarantined: bool = False
    saved_links: set[tuple[str, str]] = field(default_factory=set)
    saved_score: int = 0


# ponytail: 프로세스 메모리에 둠. 재시작하면 채점이 처음부터 시작되고, 이미 올린 격리 키는 Redis에 남음
_states: dict[str, State] = {}


def reset() -> None:
    _states.clear()


def forget(actor_id: str) -> None:
    """오탐 해제된 공격 주체의 점수를 지움. 그대로 두면 다음 요청에서 바로 다시 격리됨."""
    state = _states.get(actor_id)
    for key in [k for k, v in _states.items() if v is state]:
        del _states[key]


def _state_for(e: Event) -> State:
    # ponytail: 서로 다른 IP의 점수는 합치지 않음. 토큰 묶음 이슈에서 병합
    state = _states.get(e.actor_id) or _states.get(e.ip) or State(first_seen=e.ts, last_seen=e.ts)
    state.actor_id = state.actor_id or e.actor_id
    _states[e.ip] = state
    if state.actor_id:
        _states[state.actor_id] = state
    return state


def _is_sequential(state: State, path: str, query: str) -> bool:
    value = parse_qs(query).get("id", [""])[0]
    if not value.isdecimal():
        return False
    current = int(value)
    last, run = state.id_runs.get(path, (None, 0))
    run = run + 1 if last is not None and current == last + 1 else 1
    state.id_runs[path] = (current, run)
    return run >= SEQUENTIAL_RUN


def _is_mechanical(state: State, ts: datetime) -> bool:
    state.times.append(ts)
    if len(state.times) <= INTERVALS:
        return False
    times = list(state.times)
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    return statistics.pstdev(gaps) < MAX_STDEV


def apply(state: State, e: Event) -> None:
    """이 이벤트에서 새로 나온 신호만 더함. 같은 신호는 대상별로 한 번만."""
    parts = urlsplit(e.path)
    if parts.path == "/admin-legacy":
        state.visited_admin = True
    found = {
        "decoy": e.decoy_id in ("admin_legacy", "endless_export"),
        "hidden_guide": parts.path == "/api/internal/export" and not state.visited_admin,
        "internal_header": e.internal_header,
        "sequential_ids": _is_sequential(state, parts.path, parts.query),
        "mechanical": _is_mechanical(state, e.ts),
    }
    for signal, hit in found.items():
        if hit and signal not in state.signals:
            state.signals.add(signal)
            state.score += SCORES[signal]


async def _decoys_on() -> bool:
    return b"1" in await rds.client.hvals(rds.DECOYS_KEY)


async def _quarantine(state: State) -> None:
    new_links = state.links - state.saved_links
    changed = bool(new_links) or state.score != state.saved_score or not state.quarantined
    if state.actor_id is None:
        state.actor_id = f"A-{await rds.client.incr(rds.ACTOR_SEQ_KEY):02d}"
        _states[state.actor_id] = state
    actor = Actor(id=state.actor_id, status="quarantined", score=state.score,
                  first_seen=state.first_seen, last_seen=state.last_seen)
    await db.save_actor(actor, sorted(new_links))
    if new_links:
        await rds.client.mset({rds.quarantine_key(k, v): actor.id for k, v in new_links})
    # 저장에 실패하면 여기까지 오지 않으므로 다음 이벤트에서 다시 시도함
    state.quarantined = True
    state.saved_links |= new_links
    state.saved_score = state.score
    if changed:
        await hub.broadcast("actor_update", actor.model_dump(mode="json"))


async def process(e: Event) -> None:
    state = _state_for(e)
    state.last_seen = e.ts
    state.links.add(("ip", e.ip))
    if e.session_id:
        state.links.add(("session", e.session_id))
    if e.token:
        state.links.add(("token", e.token))
    apply(state, e)
    if state.score < THRESHOLD:
        return
    # 미끼망을 끈 시연에서는 실제 유출을 보여줘야 하므로 새로 격리하지 않음
    if state.quarantined or await _decoys_on():
        await _quarantine(state)
