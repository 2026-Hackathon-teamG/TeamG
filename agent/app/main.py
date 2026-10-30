"""
공격 에이전트 FastAPI 엔트리포인트.

POST /run 하나만 제공한다.
    {"mode": "live"}                      -> LLM 에이전트를 실제로 돌린다.
    {"mode": "replay", "run_file": "..."}  -> 녹화된 run을 재생한다. run_file을 빼면
                                             끝까지 녹화된 가장 최근 run을 쓴다.

실행은 백그라운드 스레드에서 하고 /run은 바로 응답한다. 한 번의 실행이 수 분 걸리는데
detector(/ops/demo/run)는 10초 안에 응답을 기다리기 때문이다. 실행이 끝났는지는
ops-ui와 rehearsal 모두 마지막 X-Agent-Note: __END__ 이벤트로 판단한다.
동시에 두 번 실행하면 이벤트가 섞이므로 실행 중에는 409를 돌려준다.

리뷰에서 나온 nit: 루트의 옛 agent/main.py(CLI)와 이 파일이 헷갈린다는 지적이 있었다.
이 파일이 유일한 진입점이고, 옛 CLI(agent/main.py, 템플릿 기반 Red Agent)는
이번 PR에서 agent/app/ 구조로 대체되는 대상이다.

실행:
    uvicorn app.main:app --host 0.0.0.0 --port 8004
"""

import logging
import os
import threading
from collections.abc import Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import ANTHROPIC_API_KEY, RUNS_DIR, assert_target_is_safe
from app.llm_agent import run_live
from app.replay import latest_run_file, run_replay

log = logging.getLogger(__name__)

app = FastAPI(title="공격 에이전트")

# 실행 중이면 잡혀 있음. 스레드가 끝날 때 푼다.
_running = threading.Lock()


class RunRequest(BaseModel):
    mode: str  # "live" | "replay"
    run_file: str | None = None  # mode == "replay"일 때만 사용
    speed: float = 1.0  # mode == "replay"일 때만 사용


def _start(job: Callable[[], dict], label: str) -> None:
    """job을 백그라운드에서 돌린다. 이미 실행 중이면 409."""
    if not _running.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="이미 실행 중입니다. 끝난 뒤 다시 실행하세요.")

    def work() -> None:
        try:
            log.info("%s 시작", label)
            log.info("%s 끝: %s", label, job())
        except Exception:
            log.exception("%s 실패", label)
        finally:
            _running.release()

    threading.Thread(target=work, name=label, daemon=True).start()


@app.post("/run", status_code=202)
def run(request: RunRequest) -> dict:
    if request.mode == "live":
        # 설정 문제는 스레드로 넘기기 전에 여기서 400으로 돌려준다.
        # 호출 쪽(ops-ui 등)이 "설정 문제"와 "서버 내부 오류"를 구분할 수 있게 한다.
        try:
            assert_target_is_safe()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not ANTHROPIC_API_KEY:
            raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY가 비어 있습니다. .env를 확인하세요.")
        _start(run_live, "live")
        return {"mode": "live", "status": "started"}

    if request.mode == "replay":
        run_file = request.run_file or latest_run_file()
        if not run_file:
            raise HTTPException(
                status_code=404,
                detail="재생할 녹화가 없습니다. 먼저 live 모드로 끝까지 한 번 실행하세요.",
            )
        path = run_file if os.path.isabs(run_file) else os.path.join(RUNS_DIR, run_file)
        if not os.path.isfile(path):
            raise HTTPException(status_code=404, detail=f"녹화 파일이 없습니다: {run_file}")
        _start(lambda: run_replay(run_file, speed=request.speed), "replay")
        return {"mode": "replay", "status": "started", "run_file": run_file}

    raise HTTPException(status_code=400, detail=f"알 수 없는 mode: {request.mode}")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
