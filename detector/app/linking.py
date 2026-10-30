"""공격 주체 묶음 판정. 서명 토큰은 확정, 행동 지문 유사도는 추정."""
import os
from collections.abc import Iterable

from shared import tokens

TOKEN_SECRET = os.environ.get("TOKEN_SECRET", "change-me")
MIN_SIMILARITY = 0.7


def verify(token: str | None) -> str | None:
    """서명이 맞으면 토큰의 공격 주체 id를 돌려줌."""
    verified = tokens.verify(token, TOKEN_SECRET)
    return verified[0] if verified else None


def _three_grams(paths: Iterable[str]) -> set[tuple[str, str, str]]:
    items = list(paths)
    return set(zip(items, items[1:], items[2:]))


def similar(a: Iterable[str], b: Iterable[str]) -> bool:
    grams_a, grams_b = _three_grams(a), _three_grams(b)
    if not grams_a or not grams_b:
        return False
    return len(grams_a & grams_b) / len(grams_a | grams_b) >= MIN_SIMILARITY
