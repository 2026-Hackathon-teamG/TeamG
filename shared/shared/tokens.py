"""미끼 페이지 토큰. gateway가 발급하고 gateway·detector가 검증한다.

형식: pt_<actor_id>_<page>_<hmac>   예) pt_A-01_2_3f9c0a1b2c3d4e5f
HMAC은 TOKEN_SECRET으로 "actor_id|page"를 서명한 sha256 앞 16자리.
"""
import hashlib
import hmac
import re

_PATTERN = re.compile(r"^pt_(A-\d+)_(\d+)_([0-9a-f]{16})$")


def _mac(actor_id: str, page: int, secret: str) -> str:
    return hmac.new(secret.encode(), f"{actor_id}|{page}".encode(), hashlib.sha256).hexdigest()[:16]


def sign(actor_id: str, page: int, secret: str) -> str:
    return f"pt_{actor_id}_{page}_{_mac(actor_id, page, secret)}"


def verify(token: str | None, secret: str) -> tuple[str, int] | None:
    """서명이 맞으면 (actor_id, page), 아니면 None."""
    m = _PATTERN.match(token or "")
    if not m:
        return None
    actor_id, page, mac = m.group(1), int(m.group(2)), m.group(3)
    if not hmac.compare_digest(mac, _mac(actor_id, page, secret)):
        return None
    return actor_id, page


def export_page(query_page: str | None, token: str | None, secret: str) -> int:
    """/api/internal/export가 보여 줄 페이지. 토큰이 있으면 토큰의 페이지, 없으면 page 파라미터(기본 1)."""
    verified = verify(token, secret)
    if verified:
        return verified[1]
    return int(query_page) if query_page and query_page.isdigit() and int(query_page) > 0 else 1
