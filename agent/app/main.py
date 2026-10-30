"""
공격 에이전트 FastAPI 엔트리포인트.

POST /run 하나만 제공한다.
    {"mode": "live"}                      -> LLM 에이전트를 실제로 돌린다.
    {"mode": "replay", "run_file": "..."}  -> 녹화된 run을 재생한다.

리뷰에서 나온 nit: 루트의 옛 agent/main.py(CLI)와 이 파일이 헷갈린다는 지적이 있었다.
이 파일이 유일한 진입점이고, 옛 CLI(agent/main.py, 템플릿 기반 Red Agent)는
이번 PR에서 agent/app/ 구조로 대체되는 대상이다.

실행:
    uvicorn app.main:app --host 0.0.0.0 --port 8004
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.llm_agent import run_live
from app.replay import run_replay

app = FastAPI(title="공격 에이전트")


class RunRequest(BaseModel):
    mode: str  # "live" | "replay"
    run_file: str | None = None  # mode == "replay"일 때만 사용
    speed: float = 1.0  # mode == "replay"일 때만 사용


@app.post("/run")
def run(request: RunRequest) -> dict:
    if request.mode == "live":
        try:
            result = run_live()
        except RuntimeError as exc:
            # assert_target_is_safe()가 막은 경우 여기로 떨어진다.
            # 500이 아니라 400으로 돌려줘서, 호출 쪽(ops-ui 등)이
            # "설정 문제"와 "서버 내부 오류"를 구분할 수 있게 한다.
            raise HTTPException(status_code=400, detail=str(exc))
        return {"mode": "live", **result}

    if request.mode == "replay":
        if not request.run_file:
            raise HTTPException(status_code=400, detail="replay 모드는 run_file이 필요합니다.")
        result = run_replay(request.run_file, speed=request.speed)
        return {"mode": "replay", **result}

    raise HTTPException(status_code=400, detail=f"알 수 없는 mode: {request.mode}")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}