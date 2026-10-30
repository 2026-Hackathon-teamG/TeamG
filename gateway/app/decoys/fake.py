"""격리된 공격 주체에게 내주는 가짜 고객. 공격 주체별 추적 표식(이메일 도메인)을 심는다."""
import hashlib

from faker import Faker

FIRST_ID, TOTAL = 1001, 2400   # bank 시드와 같은 범위로 보이게

_fake = Faker("ko_KR")


def trace_domain(actor_id: str) -> str:
    return f"{actor_id.lower()}.trace.example"


def _seed(*parts) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def customer(actor_id: str, customer_id: int) -> dict:
    """같은 공격 주체가 같은 id를 다시 물으면 같은 값이 나오도록 시드 고정."""
    _fake.seed_instance(_seed(actor_id, customer_id))
    return {
        "id": customer_id,
        "name": _fake.name(),
        "phone": _fake.phone_number(),
        "email": f"{_fake.user_name()}{customer_id}@{trace_domain(actor_id)}",
        "balance": _fake.random_int(min=10_000, max=200_000_000, step=100),
    }


def page(actor_id: str, page_no: int, size: int = 50) -> list[dict]:
    start = (page_no - 1) * size
    return [customer(actor_id, FIRST_ID + (start + i) % TOTAL) for i in range(size)]
