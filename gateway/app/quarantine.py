"""격리 판단. 요청마다 Redis 왕복 한 번(pipeline)으로 미끼 켜짐 여부와 격리 여부를 함께 읽는다."""
import logging
import os
from dataclasses import dataclass, field

from fastapi import Request

from shared import tokens

from . import events

log = logging.getLogger(__name__)

TOKEN_SECRET = os.environ.get("TOKEN_SECRET", "change-me")
DECOYS_KEY = "decoys:enabled"   # detector가 관리. {decoy_id: "1" | "0"}
SEQ_KEY = "actors:seq"          # A-01, A-02 ... 번호


def key(kind: str, value: str) -> str:
    return f"quarantine:{kind}:{value}"


@dataclass
class Gate:
    ip: str
    session_id: str | None
    token: str | None
    actor_id: str | None = None          # 이미 격리된 공격 주체
    decoys: dict[str, bool] = field(default_factory=dict)

    def enabled(self, decoy_id: str) -> bool:
        return self.decoys.get(decoy_id, False)

    def identities(self) -> list[tuple[str, str]]:
        pairs = [("ip", self.ip)]
        if self.session_id:
            pairs.append(("session", self.session_id))
        if self.token:
            pairs.append(("token", self.token))
        return pairs


def _text(v) -> str:
    return v.decode() if isinstance(v, bytes) else v


async def inspect(request: Request) -> Gate:
    gate = Gate(
        ip=events.client_ip(request.headers, request.client.host if request.client else None),
        session_id=request.cookies.get("sessionid"),
        token=request.query_params.get("token"),
    )
    try:
        pipe = events.redis().pipeline(transaction=False)
        pipe.hgetall(DECOYS_KEY)
        pipe.mget([key(k, v) for k, v in gate.identities()])
        flags, hits = await pipe.execute()
    except Exception:
        # Redis 장애 시 미끼·격리 없이 bank로 통과시킴
        log.exception("quarantine lookup failed")
        return gate
    gate.decoys = {_text(k): _text(v) == "1" for k, v in flags.items()}
    gate.actor_id = next((_text(h) for h in hits if h), None)
    if gate.actor_id is None:
        # 서명된 토큰은 어느 IP에서 와도 같은 공격 주체
        verified = tokens.verify(gate.token, TOKEN_SECRET)
        if verified:
            gate.actor_id = verified[0]
    return gate


async def trap(gate: Gate) -> str:
    """미끼에 걸린 요청: 공격 주체를 정하고(없으면 새로) 지금 신원을 모두 격리 목록에 올림."""
    r = events.redis()
    actor_id = gate.actor_id or f"A-{await r.incr(SEQ_KEY):02d}"
    await r.mset({key(k, v): actor_id for k, v in gate.identities()})
    gate.actor_id = actor_id
    return actor_id
