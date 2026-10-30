"""
에이전트 실행 기록기.

한 번의 실행(run)을 시작하면 runs/<timestamp>.jsonl 파일을 하나 만들고,
매 요청(tools.py의 RequestOutcome)마다 한 줄씩 JSON으로 append한다.

CLAUDE.md 규칙: 기록은 results/가 아니라 agent/runs/ 밑에 남긴다.
results/와 달리 .gitignore에 등록돼 있어야 하니, 실제 레포에 반영할 때
.gitignore에 'agent/runs/' 한 줄 있는지 꼭 확인할 것.
"""

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone

from app.config import RUNS_DIR
from app.tools import RequestOutcome


class Recorder:
    """한 번의 실행(run)에 대한 기록 파일을 관리한다."""

    def __init__(self, runs_dir: str = RUNS_DIR):
        os.makedirs(runs_dir, exist_ok=True)
        # 파일명 자체가 run_id 역할을 한다. 같은 초에 두 번 실행될 일은
        # 데모 환경에서는 거의 없다고 보고, 충돌 시엔 마이크로초까지 붙인다.
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.run_id = timestamp
        self.path = os.path.join(runs_dir, f"{timestamp}.jsonl")
        self._step = 0

    def write_meta(self, mode: str, target: str) -> None:
        """실행 맨 첫 줄에 이 run에 대한 메타정보를 남긴다.
        replay.py가 이 줄을 읽어서 어떤 target으로 재생할지 참고할 수 있다."""
        meta = {
            "type": "meta",
            "run_id": self.run_id,
            "mode": mode,
            "target": target,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self._append(meta)

    def write_outcome(self, outcome: RequestOutcome) -> None:
        """요청 하나의 결과를 한 줄로 기록한다."""
        self._step += 1
        line = {
            "type": "step",
            "step": self._step,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            **asdict(outcome),
        }
        self._append(line)

    def write_end(self, summary: str) -> None:
        """에이전트가 스스로 끝났다고 판단했을 때, 마지막에 요약 한 줄을 남긴다.
        실제 '종료 신호' 요청(X-Agent-Note: __END__)은 llm_agent.py가 별도로
        http 요청으로 보내고, 그 결과도 write_outcome으로 똑같이 기록된다.
        이 write_end는 사람이 .jsonl을 열어봤을 때 끝을 바로 알아보게 하는 용도다."""
        line = {
            "type": "end",
            "run_id": self.run_id,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }
        self._append(line)

    def _append(self, obj: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")