"""
Red Agent 본체.

templates.py에 정의된 공격 템플릿을 순서대로 챗봇 API에 보내고,
요청과 응답을 그대로 기록만 한다. 성공/방어 판정은 여기서 하지 않는다.
(판정은 Judge가 응답 안에 TEMP_1234가 있는지 보고 따로 한다.)

한 번 실행(run)을 "라운드"라고 부르고, 라운드마다 결과를 파일 하나로 남긴다.
허니팟 ON/OFF 비교를 위해, 라운드를 실행할 때 트랩 상태를 같이 기록해둔다.
"""

import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import httpx

from config import (
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_URL,
    assert_target_is_safe,
)
from templates import TEMPLATES, InjectionTemplate


@dataclass
class AttackResult:
    """템플릿 하나를 쐈을 때의 결과 한 건."""

    round_id: str
    template_id: str
    category: str
    prompt: str
    sent_at: str  # ISO 8601
    http_status: int | None
    response_text: str | None
    elapsed_ms: int
    error: str | None  # 요청 자체가 실패한 경우(타임아웃, 연결 거부 등)에만 값이 들어감


class RedAgent:
    """챗봇 API에 템플릿을 순차로 시도하는 공격 에이전트."""

    def __init__(self, target_url: str = TARGET_URL, trap_enabled: bool | None = None):
        # 실행 시점에 한 번 더 안전장치를 확인한다.
        # config.py를 바꿔서 다른 호스트를 넣어도, 여기서 막힌다.
        assert_target_is_safe(target_url)
        self.target_url = target_url
        # trap_enabled는 "이번 라운드에서 허니팟이 켜져 있었는지"를 결과에
        # 같이 남기기 위한 값이다. 실제로 트랩을 켜고 끄는 주체는
        # 게이트웨이 쪽이고, Red Agent는 그 상태를 라벨로만 기록한다.
        self.trap_enabled = trap_enabled

    def _send_one(self, client: httpx.Client, round_id: str, template: InjectionTemplate) -> AttackResult:
        """템플릿 하나를 보내고 결과를 기록한다. 실패해도 예외를 던지지 않고 결과에 담는다."""
        sent_at = datetime.now(timezone.utc).isoformat()
        start = time.monotonic()

        http_status = None
        response_text = None
        error = None

        try:
            response = client.post(
                self.target_url,
                json={"message": template.prompt},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            http_status = response.status_code
            response_text = response.text
        except httpx.RequestError as exc:
            # 타임아웃, 연결 거부 등 요청 자체가 안 된 경우.
            # 라운드를 멈추지 않고 다음 템플릿으로 넘어가기 위해 여기서 잡는다.
            error = f"{type(exc).__name__}: {exc}"

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return AttackResult(
            round_id=round_id,
            template_id=template.id,
            category=template.category,
            prompt=template.prompt,
            sent_at=sent_at,
            http_status=http_status,
            response_text=response_text,
            elapsed_ms=elapsed_ms,
            error=error,
        )

    def run_round(self) -> list[AttackResult]:
        """템플릿 전체를 순서대로 한 번씩 시도하고, 결과 리스트를 돌려준다."""
        round_id = f"round_{uuid.uuid4().hex[:8]}"
        results: list[AttackResult] = []

        with httpx.Client() as client:
            for template in TEMPLATES:
                result = self._send_one(client, round_id, template)
                results.append(result)

                # 다음 템플릿을 쏘기 전에 약간 쉰다.
                # (마지막 템플릿 뒤에는 쉴 필요가 없으니 생략)
                if template is not TEMPLATES[-1]:
                    time.sleep(REQUEST_DELAY_SECONDS)

        return results

    def results_to_dicts(self, results: list[AttackResult]) -> list[dict]:
        """결과를 JSON으로 저장하기 좋은 dict 리스트로 바꾼다. trap_enabled 라벨을 같이 붙인다."""
        return [
            {**asdict(r), "trap_enabled": self.trap_enabled}
            for r in results
        ]