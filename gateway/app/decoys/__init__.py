import asyncio
import random

# 실제 API처럼 보이도록 미끼 응답에 넣는 지연(초). 테스트에서는 0으로 바꿈
DELAY = (0.1, 0.3)


async def delay() -> None:
    lo, hi = DELAY
    if hi > 0:
        await asyncio.sleep(random.uniform(lo, hi))
