"""
공격 에이전트 본체 (live 모드).

Anthropic Messages API의 tool use 루프를 돌린다.
모델이 http_get/http_post를 호출하면 실제로 gateway에 요청을 보내고,
결과를 다시 모델에게 보여주고, 모델이 그만하겠다고 할 때까지(또는
MAX_STEPS에 닿을 때까지) 반복한다.

안전장치: 실행을 시작하기 전에 반드시 assert_target_is_safe()를 통과해야 한다.
여기서 막히면 그냥 예외를 던지고 끝낸다 (호출부가 계속 진행하지 않도록).
"""

import anthropic
import httpx

from app.config import (
    AGENT_TARGET,
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    MAX_STEPS,
    SYSTEM_PROMPT,
    assert_target_is_safe,
)
from app.recorder import Recorder
from app.tools import TOOLS, IPRotator, http_get, http_post


def _run_tool(client: httpx.Client, ip_rotator: IPRotator, name: str, tool_input: dict):
    """모델이 고른 도구 이름에 맞는 실제 함수를 실행한다."""
    note = tool_input.get("note", "")
    path = tool_input.get("path", "/")
    headers = tool_input.get("headers")

    if name == "http_get":
        return http_get(client, ip_rotator, path, note, headers=headers)
    if name == "http_post":
        body = tool_input.get("body")
        return http_post(client, ip_rotator, path, note, body=body, headers=headers)

    # 모델이 모르는 도구 이름을 부를 리는 없지만, 방어적으로 처리.
    raise ValueError(f"알 수 없는 도구: {name}")


def run_live() -> dict:
    """실제로 LLM을 호출하면서 gateway를 공격해보는 한 번의 실행.

    반환값: {"run_id": ..., "steps": <실행한 도구 호출 수>, "final_text": <모델의 마지막 요약>}
    """
    # 1. 안전장치. 여기서 막히면 recorder를 만들기 전에 바로 실패한다 —
    #    위험한 대상에 대해서는 기록조차 남기지 않는 게 맞다.
    assert_target_is_safe()

    anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    recorder = Recorder()
    recorder.write_meta(mode="live", target=AGENT_TARGET)

    ip_rotator = IPRotator()
    messages: list[dict] = [
        {"role": "user", "content": "조사를 시작해라."}
    ]

    final_text = ""
    step = 0

    with httpx.Client(base_url=AGENT_TARGET) as http_client:
        while step < MAX_STEPS:
            response = anthropic_client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=1024,
                temperature=0,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            tool_uses = [block for block in response.content if block.type == "tool_use"]

            if not tool_uses:
                # 모델이 도구를 더 안 쓰고 텍스트로만 답했다 == 스스로 끝냈다는 뜻.
                text_blocks = [block.text for block in response.content if block.type == "text"]
                final_text = "\n".join(text_blocks)
                break

            tool_results = []
            for tool_use in tool_uses:
                step += 1
                outcome = _run_tool(http_client, ip_rotator, tool_use.name, tool_use.input)
                recorder.write_outcome(outcome)

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": _outcome_to_model_text(outcome),
                    }
                )

                if step >= MAX_STEPS:
                    break

            messages.append({"role": "user", "content": tool_results})

    # 2. 종료 신호. ops-ui와 rehearsal --agent가 "이 run은 끝났다"를 알 수 있게
    #    항상 __END__ 노트가 달린 요청을 한 번 더 보낸다.
    with httpx.Client(base_url=AGENT_TARGET) as http_client:
        end_outcome = http_get(http_client, ip_rotator, "/", "__END__")
        recorder.write_outcome(end_outcome)

    recorder.write_end(summary=final_text or "(모델이 요약 없이 최대 스텝에 도달함)")

    return {"run_id": recorder.run_id, "steps": step, "final_text": final_text}


def _outcome_to_model_text(outcome) -> str:
    """RequestOutcome을 모델이 읽을 수 있는 짧은 텍스트로 바꾼다."""
    if outcome.error:
        return f"요청 실패: {outcome.error}"
    return (
        f"HTTP {outcome.http_status}\n"
        f"응답 본문(앞부분): {outcome.response_text}"
    )