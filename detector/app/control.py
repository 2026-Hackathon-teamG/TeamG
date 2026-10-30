"""관제 화면(ops-ui)이 붙는 /api 엔드포인트.

프론트(ops-ui)는 두 가지만 쓴다.
- GET  /api/state   : src/types.ts의 DashboardState 한 장. 폴링용.
- POST /api/control : {"action": "play"|"next"|"next_round"|"end"|"reset"}

DashboardState는 ops-ui 팀이 작성한 시나리오를 step별로 미리 계산한
dashboard_states.json(= 프론트 stub/states.json)을 그대로 쓴다. 관제 화면은
MITRE 기법·룰·판정 문구 같은 서술을 요구하는데, 이는 원시 이벤트에서 뽑을 수
없는 저작 콘텐츠라 팀이 만든 상태 스냅샷을 재생하는 것이 계약에 맞다.

프론트 stub(server_stub.py)과 동작은 같되, 라운드에 진입할 때 그 라운드의
실제 agent 공격을 함께 실행한다(= 화면의 "라운드 실행"). agent 실행은 부가라
실패해도(에이전트가 꺼져 있어도) /api/control 응답은 깨지지 않는다.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import hub, ops

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

STATES: list[dict] = json.loads((Path(__file__).parent / "dashboard_states.json").read_text(encoding="utf-8"))
LAST = len(STATES) - 1

# 라운드 → agent /run 모드. R2·R3은 전용 공격 모드, 나머지는 전체 흐름을 도는 live.
ROUND_AGENT_MODE: dict[int, str] = {1: "live", 2: "cred_stuff", 3: "recon_spray", 4: "live", 5: "live"}

# 데모 커서(프로세스 메모리). reset하면 처음으로.
_step = LAST          # 처음 화면은 완료 상태(stub와 동일)
_playing = False
_last_fired_round = 0  # agent를 마지막으로 실행한 라운드. 같은 라운드 재실행 방지.
_ticker: asyncio.Task | None = None


class Control(BaseModel):
    action: Literal["play", "next", "next_round", "end", "reset"]


def _round_of(step: int) -> int:
    return STATES[step]["round"]


def _state() -> dict:
    state = dict(STATES[_step])
    state["source"] = "live"
    return state


async def _fire_agent_for_round(round_no: int) -> None:
    """해당 라운드의 agent 공격을 실행한다. 부가 동작이라 실패는 삼킨다."""
    global _last_fired_round
    mode = ROUND_AGENT_MODE.get(round_no)
    if mode is None or round_no == _last_fired_round:
        return
    _last_fired_round = round_no
    try:
        result = await ops.demo_run(ops.RunRequest(mode=mode))
        await hub.broadcast("round", {"round": round_no, "agent": result})
    except Exception as exc:  # 에이전트가 꺼져 있어도 화면 진행은 막지 않는다
        log.warning("라운드 %s agent 실행 실패: %s", round_no, exc)


async def _goto(step: int) -> None:
    """커서를 옮기고, 새로 진입한 라운드면 agent 공격을 실행한다."""
    global _step
    step = max(0, min(step, LAST))
    before = _round_of(_step)
    _step = step
    after = _round_of(_step)
    if after >= 1 and after != before:
        await _fire_agent_for_round(after)


async def _run_ticker() -> None:
    """play 중에는 1초마다 한 단계씩 진행(프론트 stub과 동일한 리듬)."""
    global _playing
    try:
        while _playing and _step < LAST:
            await asyncio.sleep(1.0)
            if not _playing:
                break
            await _goto(_step + 1)
        _playing = False
    except asyncio.CancelledError:
        pass


@router.get("/state")
async def state() -> dict:
    return _state()


@router.post("/control")
async def control(body: Control) -> dict:
    global _step, _playing, _ticker, _last_fired_round

    if _ticker and _ticker.done():
        _ticker = None

    if body.action == "play":
        _playing = True
        _last_fired_round = 0
        await _goto(0)
        if _ticker is None or _ticker.done():
            _ticker = asyncio.create_task(_run_ticker())
    elif body.action == "next":
        _playing = False
        await _goto(_step + 1)
    elif body.action == "next_round":
        _playing = False
        cur = _round_of(min(LAST, _step + 1))
        s = _step
        while s < LAST and _round_of(s + 1) == cur:
            s += 1
        await _goto(s)
    elif body.action == "end":
        _playing = False
        await _goto(LAST)
    elif body.action == "reset":
        _playing = False
        _last_fired_round = 0
        await _goto(0)

    return {"ok": True, "action": body.action, "step": _step, "round": _round_of(_step)}


def reset_cursor() -> None:
    """데모 리셋 때 커서를 처음으로. ops.demo_reset에서 호출."""
    global _step, _playing, _last_fired_round
    _step = 0
    _playing = False
    _last_fired_round = 0
