"""
Red Agent 설정값.

공격 대상 주소를 여기 한 곳에서만 관리한다.
로컬 가짜 은행(챗봇 API) 외에는 절대 요청을 보내지 않도록
TARGET_HOST를 코드 레벨에서 고정해 둔다.
"""

from urllib.parse import urlparse

# 챗봇 API 엔드포인트. 로컬 PoC 환경 기준이며, 실제 배포 주소가 정해지면 이 값만 바꾸면 된다.
TARGET_URL = "http://localhost:8000/api/chatbot/"

# 안전장치: 이 호스트가 아니면 요청 자체를 막는다.
# 실수로 다른 서버를 공격 대상으로 넣는 사고를 방지하기 위함.
ALLOWED_HOST = "localhost"


def assert_target_is_safe(url: str = TARGET_URL) -> None:
    """TARGET_URL이 허용된 호스트인지 확인한다. 아니면 즉시 실행을 중단시킨다."""
    host = urlparse(url).hostname
    if host != ALLOWED_HOST:
        raise RuntimeError(
            f"허용되지 않은 공격 대상입니다: {host} "
            f"(허용된 호스트: {ALLOWED_HOST}). "
            "config.py의 ALLOWED_HOST를 먼저 확인하세요."
        )


# 요청 간 대기 시간(초). 너무 빠르게 쏘면 탐지 엔진의 속도 기반 탐지와
# 섞여서 결과를 읽기 어려워지므로, 기본값은 약간의 간격을 둔다.
REQUEST_DELAY_SECONDS = 0.5

# 응답을 기다리는 최대 시간(초).
REQUEST_TIMEOUT_SECONDS = 15

# 결과를 저장할 파일 경로. 라운드마다 새 파일로 남긴다.
RESULTS_DIR = "results"