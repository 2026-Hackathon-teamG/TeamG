"""로그인 실패 폭주를 막는 차단 룰.

지금은 R1만 구현: 같은 IP가 짧은 시간에 로그인 실패를 반복하면 그 IP를 일정 시간 차단한다.
격리(미끼로 보냄)와 달리 차단은 gateway가 요청을 429로 되돌린다.
공격 주체 단위(R2), 작전 단위(R3·R4)는 다음 슬라이스에서 scoring 쪽과 함께 붙인다.

차단 상태는 Redis 키(block:ip:<ip>)에 TTL과 함께 두고, 메모리에는 실패 시각만 둔다.
detector를 재시작하면 창은 비지만 이미 올린 차단 키는 Redis에 남는다.
"""
import logging
from collections import defaultdict, deque
from datetime import datetime

from shared import Event

from . import hub, rds

log = logging.getLogger(__name__)

# R1: 같은 IP가 WINDOW초에 로그인 실패 THRESHOLD회면 BLOCK_SECONDS초 차단
WINDOW = 60
THRESHOLD = 5
BLOCK_SECONDS = 15 * 60

_fails: dict[str, deque[datetime]] = defaultdict(deque)
_blocked: set[str] = set()   # 이미 차단을 알린 IP (중복 방송 방지)


def reset() -> None:
    _fails.clear()
    _blocked.clear()


def _recent_fail_count(ip: str, now: datetime) -> int:
    fails = _fails[ip]
    fails.append(now)
    cutoff = now.timestamp() - WINDOW
    while fails and fails[0].timestamp() < cutoff:
        fails.popleft()
    return len(fails)


async def process(e: Event) -> None:
    """로그인 실패 이벤트만 본다. 임계치를 넘으면 IP를 차단한다."""
    if e.login_result != "fail":
        return
    if _recent_fail_count(e.ip, e.ts) < THRESHOLD:
        return
    await rds.client.set(rds.block_key("ip", e.ip), "R1", ex=BLOCK_SECONDS)
    if e.ip not in _blocked:
        _blocked.add(e.ip)
        await hub.broadcast("block", {"kind": "ip", "value": e.ip, "rule": "R1", "seconds": BLOCK_SECONDS})
