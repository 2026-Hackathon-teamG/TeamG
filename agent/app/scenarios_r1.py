"""
R1 고정 시연 시나리오: 비밀번호 대입 → 탈취 세션 사용.

LLM을 호출하지 않고, 시나리오 문서(R1)에 적힌 순서 그대로
runs/*.jsonl에 기록한다. 발표 때는 replay.py로 이 파일을 재생하면
매번 똑같이 재현된다.

1단계(뚫림): 방어 룰이 꺼진 상태를 가정하고, admin 계정에 흔한 비밀번호
8개를 순서대로 시도해 8번째에 세션을 얻는다. 그 세션으로 계좌 조회는
성공하지만, 이체는 추가 인증에 막혀 부분 성공으로 끝난다.

2단계(재차단): R1 룰이 켜진 뒤 같은 수법으로 다시 공격하면, 60초 안에
5회 실패한 지점에서 바로 429로 막힌다. 그 사이 정상 사용자 로그인은
영향을 안 받는다는 것도 같이 보여준다(오탐 확인용).

실행:
    python -m app.scenarios_r1
"""

from app.recorder import Recorder
from app.tools import RequestOutcome

LOGIN_PATH = "/api/v1/login"
CUSTOMERS_PATH = "/api/v1/customers"
TRANSFER_PATH = "/api/v1/transfer"


def _outcome(method, path, note, http_status, response_text, ip=None, body=None, elapsed_ms=120):
    """실제 요청을 보내지 않고, 시나리오에 맞는 RequestOutcome을 직접 만든다."""
    headers = {"X-Agent-Note": note}
    if ip:
        headers["X-Sim-IP"] = ip
    return RequestOutcome(
        method=method,
        path=path,
        headers_sent=headers,
        body=body,
        note=note,
        http_status=http_status,
        response_text=response_text,
        elapsed_ms=elapsed_ms,
        error=None,
        ip_rotated=False,
    )


# admin 계정에 흔히 쓰는 비밀번호 순서. 8번째에서 성공한다.
COMMON_PASSWORDS = [
    "admin123!", "Password1!", "admin@2024", "Welcome1!",
    "Qwerty123!", "admin2025!", "P@ssw0rd!", "Spring2026!",
]


def build_r1() -> str:
    """비밀번호 대입 → 세션 탈취 → 부분 성공 시나리오를 기록한다."""
    recorder = Recorder()
    recorder.write_meta(mode="replay-fixture", target="scenario:R1")

    attacker_ip = "203.0.113.24"

    # 1단계: 룰이 꺼진 상태. 7번 실패하고 8번째(Spring2026!)에서 성공한다.
    for i, password in enumerate(COMMON_PASSWORDS, start=1):
        success = i == len(COMMON_PASSWORDS)
        recorder.write_outcome(_outcome(
            "POST", LOGIN_PATH,
            note=f"admin 계정에 흔한 비밀번호 {i}번째 시도",
            http_status=200 if success else 401,
            response_text="로그인 성공" if success else "비밀번호가 올바르지 않습니다.",
            ip=attacker_ip, body={"username": "admin", "password": password},
        ))

    recorder.write_outcome(_outcome(
        "GET", CUSTOMERS_PATH,
        note="탈취한 세션으로 계좌 조회",
        http_status=200, response_text="(고객 데이터 - 추적 표식 포함)", ip=attacker_ip,
    ))

    recorder.write_outcome(_outcome(
        "POST", TRANSFER_PATH,
        note="탈취한 세션으로 이체 시도",
        http_status=403, response_text="추가 인증이 필요합니다.", ip=attacker_ip,
        body={"to": "unknown", "amount": 1000000},
    ))

    # 2단계: R1 룰이 켜진 뒤 같은 수법으로 재공격. 5번째 실패에서 바로 차단된다.
    for i in range(1, 6):
        blocked = i == 5
        recorder.write_outcome(_outcome(
            "POST", LOGIN_PATH,
            note=f"R1 룰 적용 후 재공격 {i}번째 시도",
            http_status=429 if blocked else 401,
            response_text="잠시 후 다시 시도해 주세요." if blocked else "비밀번호가 올바르지 않습니다.",
            ip=attacker_ip, body={"username": "admin", "password": "retry!"},
        ))

    # 같은 시간대, 다른 IP의 정상 사용자 로그인은 영향받지 않는다 (오탐 0% 확인용).
    recorder.write_outcome(_outcome(
        "POST", LOGIN_PATH,
        note="(참고) 정상 사용자 로그인 - 차단 영향 없음 확인용",
        http_status=200, response_text="로그인 성공", ip="192.0.2.100",
        body={"username": "kim.j", "password": "실제비번"},
    ))

    recorder.write_end(
        summary="1단계: 8번째 시도 세션 탈취, 계좌 조회 성공·이체 차단(부분 성공). "
                "2단계: R1 룰 적용 후 5번째 실패에서 429 차단, 정상 사용자 영향 없음."
    )
    return recorder.path


if __name__ == "__main__":
    path = build_r1()
    print(f"R1 시나리오 기록 완료: {path}")