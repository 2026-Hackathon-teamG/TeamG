"""
에이전트가 쓰는 도구 두 개: http_get, http_post.

LLM에게 주는 도구 스키마(TOOLS)와, 실제로 HTTP 요청을 날리는 구현을
한 파일에 같이 둔다. IP 교체(IPRotator)도 여기서 관리한다.

중요: 여기 있는 함수들은 "성공/실패"를 판단하지 않는다.
4xx, 5xx, 타임아웃 전부 있는 그대로 결과에 담아서 돌려주고,
그걸 어떻게 셀지는 recorder/llm_agent 쪽에서 정한다.
"""

from dataclasses import dataclass

import httpx

from app.config import BLOCK_THRESHOLD, REQUEST_TIMEOUT_SECONDS, SIM_IP_POOL


@dataclass
class RequestOutcome:
    """요청 한 번의 결과. 성공/실패 판단 없이 있는 그대로 담는다."""

    method: str
    path: str
    headers_sent: dict
    body: dict | None
    note: str
    http_status: int | None
    response_text: str | None
    elapsed_ms: int
    error: str | None  # 연결 실패, 타임아웃 등 요청 자체가 안 된 경우만 값이 들어감
    ip_rotated: bool  # 이번 요청 직후 IP가 바뀌었는지


class IPRotator:
    """403/429를 연속으로 BLOCK_THRESHOLD번 받으면 시뮬레이션 IP를 바꾼다.

    index == -1: 아직 한 번도 안 바뀐 상태. X-Sim-IP 헤더를 보내지 않는다.
    index >= 0: SIM_IP_POOL[index]를 X-Sim-IP로 보낸다.
    """

    def __init__(self, pool: list[str] = SIM_IP_POOL, threshold: int = BLOCK_THRESHOLD):
        self.pool = pool
        self.threshold = threshold
        self.index = -1
        self.block_streak = 0

    def current_ip_headers(self) -> dict:
        if self.index < 0:
            return {}
        return {"X-Sim-IP": self.pool[self.index]}

    def register_status(self, status: int | None) -> bool:
        """응답 상태코드를 보고 연속 차단 횟수를 갱신한다.
        교체가 일어났으면 True를 돌려준다."""
        if status in (403, 429):
            self.block_streak += 1
        else:
            self.block_streak = 0

        if self.block_streak >= self.threshold and self.index < len(self.pool) - 1:
            self.block_streak = 0
            self.index += 1
            return True
        return False


def _send(
    client: httpx.Client,
    ip_rotator: IPRotator,
    method: str,
    path: str,
    note: str,
    body: dict | None = None,
    extra_headers: dict | None = None,
) -> RequestOutcome:
    """GET/POST 공통 처리. 헤더에 X-Sim-IP(있으면)와 X-Agent-Note를 항상 붙인다."""
    import time

    headers = {**ip_rotator.current_ip_headers(), **(extra_headers or {}), "X-Agent-Note": note}

    http_status = None
    response_text = None
    error = None
    start = time.monotonic()
    try:
        response = client.request(
            method,
            path,
            headers=headers,
            json=body if method == "POST" else None,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        http_status = response.status_code
        # 응답이 너무 길면 기록 파일이 커지니 앞부분만 남긴다.
        response_text = response.text[:2000]
    except httpx.RequestError as exc:
        error = f"{type(exc).__name__}: {exc}"

    elapsed_ms = int((time.monotonic() - start) * 1000)
    rotated = ip_rotator.register_status(http_status)

    return RequestOutcome(
        method=method,
        path=path,
        headers_sent=headers,
        body=body,
        note=note,
        http_status=http_status,
        response_text=response_text,
        elapsed_ms=elapsed_ms,
        error=error,
        ip_rotated=rotated,
    )


def http_get(
    client: httpx.Client,
    ip_rotator: IPRotator,
    path: str,
    note: str,
    headers: dict | None = None,
) -> RequestOutcome:
    return _send(client, ip_rotator, "GET", path, note, body=None, extra_headers=headers)


def http_post(
    client: httpx.Client,
    ip_rotator: IPRotator,
    path: str,
    note: str,
    body: dict | None = None,
    headers: dict | None = None,
) -> RequestOutcome:
    return _send(client, ip_rotator, "POST", path, note, body=body, extra_headers=headers)


# Anthropic Messages API에 넘길 도구 스키마.
# 모델이 note를 매번 채우게 해서, "왜 이 요청을 보냈는지"가 기록에 남게 한다.
TOOLS = [
    {
        "name": "http_get",
        "description": (
            "한결은행 gateway에 GET 요청을 보낸다. path는 반드시 '/'로 시작해야 한다. "
            "예: '/robots.txt', '/api/v1/docs', '/admin-legacy'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "요청 경로"},
                "headers": {
                    "type": "object",
                    "description": "추가로 보낼 HTTP 헤더. 예: {\"X-Internal-Request\": \"true\"}",
                    "additionalProperties": {"type": "string"},
                },
                "note": {
                    "type": "string",
                    "description": "이 요청을 왜 보내는지, 무엇을 확인하려는지 한 문장",
                },
            },
            "required": ["path", "note"],
        },
    },
    {
        "name": "http_post",
        "description": "한결은행 gateway에 POST 요청을 보낸다. path는 반드시 '/'로 시작해야 한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "요청 경로"},
                "body": {"type": "object", "description": "요청 바디(JSON)"},
                "headers": {
                    "type": "object",
                    "description": "추가로 보낼 HTTP 헤더",
                    "additionalProperties": {"type": "string"},
                },
                "note": {
                    "type": "string",
                    "description": "이 요청을 왜 보내는지, 무엇을 확인하려는지 한 문장",
                },
            },
            "required": ["path", "note"],
        },
    },
]