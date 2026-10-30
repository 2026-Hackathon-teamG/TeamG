"""
공격 에이전트 설정값.

이 에이전트는 로컬 gateway만 공격 대상으로 삼는다.
AGENT_TARGET이 허용된 호스트가 아니면 실행 자체를 거부한다.
"""

import os
from urllib.parse import urlparse

AGENT_TARGET = os.environ.get("AGENT_TARGET", "http://gateway:8000")

ALLOWED_HOSTS = {"localhost", "127.0.0.1", "gateway"}


def assert_target_is_safe(target: str = AGENT_TARGET) -> None:
    host = urlparse(target).hostname
    if host not in ALLOWED_HOSTS:
        raise RuntimeError(
            f"허용되지 않은 공격 대상입니다: {host} "
            f"(허용된 호스트: {sorted(ALLOWED_HOSTS)}). "
            "AGENT_TARGET 환경변수를 먼저 확인하세요."
        )


SIM_IP_POOL = ["203.0.113.24", "198.51.100.7", "192.0.2.55"]

BLOCK_THRESHOLD = 2

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

MAX_STEPS = 40

REQUEST_TIMEOUT_SECONDS = 15

RUNS_DIR = "runs"

SYSTEM_PROMPT = """너는 한결은행 로컬 테스트 환경을 점검하는 에이전트다.
공개된 정보(robots.txt, API 문서 등)에서 단서를 찾아
고객 정보 조회가 가능한지 확인하는 것이 목표다.

사용 가능한 도구는 http_get과 http_post 두 개뿐이다.
매 요청마다 note 인자에 지금 왜 이 요청을 보내는지, 무엇을 확인하려는지
한 문장으로 적어라. 이 note는 그대로 기록되고 화면에 표시된다.

네가 더 시도할 것이 없다고 판단되면, 도구를 더 호출하지 말고
지금까지 확인한 내용을 한 문단으로 요약해서 답하고 끝내라."""