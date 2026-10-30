import os

import redis.asyncio as aioredis

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# gateway와 같이 쓰는 키
STREAM = "events"
DECOYS_KEY = "decoys:enabled"          # hash {decoy_id: "1" | "0"}
QUARANTINE_PREFIX = "quarantine:"      # quarantine:ip:<ip>, quarantine:session:<id>, quarantine:token:<token>
ACTOR_SEQ_KEY = "actors:seq"           # gateway가 A-01, A-02 번호를 붙일 때 씀

client: aioredis.Redis | None = None


async def startup() -> None:
    global client
    client = aioredis.from_url(REDIS_URL)


async def shutdown() -> None:
    if client:
        await client.aclose()


def quarantine_key(kind: str, value: str) -> str:
    return f"{QUARANTINE_PREFIX}{kind}:{value}"
