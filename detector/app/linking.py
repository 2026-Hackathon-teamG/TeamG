"""공격 주체 묶음 판정. 서명 토큰은 확정, 행동 지문 유사도는 추정."""
import hashlib
import hmac
import os
import re
from collections.abc import Iterable

TOKEN_SECRET = os.environ.get("TOKEN_SECRET", "")
MIN_SIMILARITY = 0.7

_TOKEN = re.compile(r"pt_(A-[0-9]+)_([0-9]+)_([0-9a-f]{64})")


def sign(actor_id: str, page: int | str) -> str:
    """HMAC-SHA256 hex. 미끼 쪽 next_token 발급과 같은 방식이어야 함."""
    return hmac.new(TOKEN_SECRET.encode(), f"{actor_id}|{page}".encode(), hashlib.sha256).hexdigest()


def verify(token: str | None) -> str | None:
    """서명이 맞으면 토큰의 공격 주체 id를 돌려줌. 비밀값이 없으면 어떤 토큰도 믿지 않음."""
    match = _TOKEN.fullmatch(token or "")
    if not match or not TOKEN_SECRET:
        return None
    actor_id, page, signature = match.groups()
    return actor_id if hmac.compare_digest(signature, sign(actor_id, page)) else None


def _three_grams(paths: Iterable[str]) -> set[tuple[str, str, str]]:
    items = list(paths)
    return set(zip(items, items[1:], items[2:]))


def similar(a: Iterable[str], b: Iterable[str]) -> bool:
    grams_a, grams_b = _three_grams(a), _three_grams(b)
    if not grams_a or not grams_b:
        return False
    return len(grams_a & grams_b) / len(grams_a | grams_b) >= MIN_SIMILARITY
