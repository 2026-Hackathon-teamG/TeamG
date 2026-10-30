"""서비스 공용 모델. 바꿀 때는 팀에 먼저 알립니다."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

DecoyId = Literal["robots", "admin_legacy", "docs_bait", "endless_export"]


class Event(BaseModel):
    id: str                  # "evt_" + ulid
    ts: datetime
    ip: str
    method: str
    path: str                # 쿼리 포함
    status: int
    session_id: str | None = None
    ua: str | None = None
    header_hash: str         # 헤더 이름 순서의 sha1 앞 6자리
    decoy_id: DecoyId | None = None
    token: str | None = None
    actor_id: str | None = None     # gateway가 아는 경우만
    routed_to: Literal["bank", "decoy"]
    records_out: int = 0     # 이 응답으로 나간 레코드 수
    agent_note: str | None = None   # 시연용. X-Agent-Note 헤더 값


class Actor(BaseModel):
    id: str                  # "A-01", "A-02" ...
    status: Literal["watching", "quarantined", "released"]
    score: int = 0
    first_seen: datetime
    last_seen: datetime


class ActorLink(BaseModel):
    actor_id: str
    kind: Literal["ip", "session", "token", "fingerprint"]
    value: str
    confidence: Literal["확정", "추정"]


class Decoy(BaseModel):
    id: DecoyId
    kind: str
    path: str
    enabled: bool = True


class CanaryToken(BaseModel):
    token: str
    actor_id: str
    page: int
    ip: str
    issued_at: datetime
