"""로그인 실패 폭주를 막는 차단 룰.

- R1: 같은 IP가 짧은 시간에 로그인 실패를 반복하면 그 IP를 차단한다.
- R2: IP를 바꿔 가며 공격하면 R1을 피한다. 그래서 같은 브라우저 지문(헤더 순서 + User-Agent)
  으로 들어온 실패를 IP와 상관없이 합산해, 임계치를 넘으면 그 지문의 모든 IP를 함께 차단한다.
  "IP가 바뀌어도 같은 공격자로 묶는다"는 핵심 주장을 로그인 차단에 적용한 것.

격리(미끼로 보냄)와 달리 차단은 gateway가 요청을 429로 되돌린다.
작전 단위(R3·R4)는 다음 슬라이스에서 붙인다.

차단 상태는 Redis 키(block:ip:<ip>)에 TTL과 함께 두고, 메모리에는 실패 시각만 둔다.
detector를 재시작하면 창은 비지만 이미 올린 차단 키는 Redis에 남는다.
"""
import logging
from collections import defaultdict, deque
from datetime import datetime

from shared import Event

from . import hub, rds

log = logging.getLogger(__name__)

# WINDOW초에 로그인 실패 THRESHOLD회면 BLOCK_SECONDS초 차단
WINDOW = 60
THRESHOLD = 5
BLOCK_SECONDS = 15 * 60

_fails: dict[str, deque[datetime]] = defaultdict(deque)          # R1: ip -> 실패 시각
_fp_fails: dict[str, deque[tuple[str, datetime]]] = defaultdict(deque)   # R2: 지문 -> (ip, 실패 시각)
_blocked: set[str] = set()   # 이미 차단을 알린 ip (중복 방송 방지)


def reset() -> None:
    _fails.clear()
    _fp_fails.clear()
    _blocked.clear()


def _recent_fail_count(ip: str, now: datetime) -> int:
    fails = _fails[ip]
    fails.append(now)
    cutoff = now.timestamp() - WINDOW
    while fails and fails[0].timestamp() < cutoff:
        fails.popleft()
    return len(fails)


def _fingerprint(e: Event) -> str:
    return f"{e.header_hash}|{e.ua or ''}"


def _recent_fp(fp: str, now: datetime) -> deque[tuple[str, datetime]]:
    fails = _fp_fails[fp]
    cutoff = now.timestamp() - WINDOW
    while fails and fails[0][1].timestamp() < cutoff:
        fails.popleft()
    return fails


async def _block(ip: str, rule: str) -> None:
    await rds.client.set(rds.block_key("ip", ip), rule, ex=BLOCK_SECONDS)
    if ip not in _blocked:
        _blocked.add(ip)
        await hub.broadcast("block", {"kind": "ip", "value": ip, "rule": rule, "seconds": BLOCK_SECONDS})


async def process(e: Event) -> None:
    """로그인 실패 이벤트만 본다. 임계치를 넘으면 IP를 차단한다."""
    if e.login_result != "fail":
        return

    # R1: 같은 IP의 실패를 센다
    if _recent_fail_count(e.ip, e.ts) >= THRESHOLD:
        await _block(e.ip, "R1")

    # R2: 같은 지문으로 IP를 바꿔 가며 실패하면 합산해 그 지문의 모든 IP를 차단
    fails = _recent_fp(_fingerprint(e), e.ts)
    fails.append((e.ip, e.ts))
    ips = {ip for ip, _ in fails}
    if len(fails) >= THRESHOLD and len(ips) >= 2:
        for ip in ips:
            await _block(ip, "R2")
