"""
재생(replay) 모드.

live 모드로 한 번 녹화해둔 runs/<timestamp>.jsonl을 읽어서,
LLM을 다시 호출하지 않고 기록된 요청들을 원래 순서/간격대로 그대로 다시 보낸다.

발표 중 네트워크나 API가 불안정해도 무조건 같은 장면이 나오게 하기 위한
데모용 안전장치다. 그래서 여기서는 녹화 당시의 경로/바디/헤더를 그대로
재전송하는 것 자체가 목적이고, 새로운 판단은 하지 않는다.
"""

import json
import os
import time
from datetime import datetime

import httpx

from app.config import AGENT_TARGET, REQUEST_TIMEOUT_SECONDS, RUNS_DIR


def _load_steps(run_file: str) -> tuple[dict, list[dict]]:
    """run_file(.jsonl)을 읽어서 (meta, step 목록)을 돌려준다."""
    meta = None
    steps = []
    with open(run_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("type") == "meta":
                meta = obj
            elif obj.get("type") == "step":
                steps.append(obj)
            # type == "end"는 재생에 필요 없어서 건너뜀.

    if meta is None:
        raise ValueError(f"{run_file}에 meta 줄이 없습니다 (올바른 run 파일인지 확인하세요).")

    return meta, steps


def run_replay(run_file: str, speed: float = 1.0) -> dict:
    """녹화된 run_file을 재생한다.

    run_file: RUNS_DIR 기준 상대경로 또는 절대경로 둘 다 받는다.
    speed: 1.0이면 녹화 당시 간격 그대로, 2.0이면 2배 빠르게.
    """
    if not os.path.isabs(run_file):
        run_file = os.path.join(RUNS_DIR, run_file)

    meta, steps = _load_steps(run_file)
    target = meta.get("target", AGENT_TARGET)

    replayed = 0
    prev_time = None

    with httpx.Client(base_url=target) as client:
        for step in steps:
            # 녹화 당시 기록 시각 간격만큼 쉬어서, 실제 공격이 진행되는 듯한
            # 리듬을 그대로 재현한다.
            current_time = datetime.fromisoformat(step["recorded_at"])
            if prev_time is not None:
                gap_seconds = (current_time - prev_time).total_seconds() / speed
                if gap_seconds > 0:
                    time.sleep(min(gap_seconds, 5.0))  # 데모 중 너무 오래 끌지 않게 상한을 둔다.
            prev_time = current_time

            headers = step.get("headers_sent", {})
            method = step.get("method", "GET")
            path = step.get("path", "/")
            body = step.get("body")

            try:
                client.request(
                    method,
                    path,
                    headers=headers,
                    json=body if method == "POST" else None,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except httpx.RequestError:
                # 재생 중 실제 요청이 실패해도(예: gateway가 그 순간 응답이 늦음)
                # 데모 흐름 자체는 끊기지 않게 다음 스텝으로 계속 진행한다.
                pass

            replayed += 1

    return {"run_id": meta.get("run_id"), "replayed_steps": replayed, "target": target}