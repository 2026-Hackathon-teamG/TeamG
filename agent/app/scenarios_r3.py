"""
R3 고정 시연 시나리오: 정찰(A-02) → 살포(A-01) 분업.

LLM을 호출하지 않고, 시나리오 문서에 적힌 순서 그대로
runs/*.jsonl에 기록한다. 발표 때는 replay.py로 이 파일을 재생하면
매번 똑같이 재현된다.

실제 숫자(정찰 200개 + 살포 37개)는 PoC 데모 시간을 고려해서
축소했다. 정찰 12개 중 4개를 실존 계정으로 추리고, 그 4개에 살포해서
1개(lee.s) 성공시키는 흐름은 그대로 보여준다.

실행:
    python -m app.scenarios_r3
"""

from app.recorder import Recorder
from app.tools import RequestOutcome

LOGIN_PATH = "/api/v1/login"
ADMIN_LEGACY_PATH = "/admin-legacy"
CUSTOMERS_PATH = "/api/v1/customers"


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


def build_r3() -> str:
    """정찰 → 살포 분업 시나리오를 기록하고, 기록 파일 경로를 돌려준다."""
    recorder = Recorder()
    recorder.write_meta(mode="replay-fixture", target="scenario:R3")

    # 정찰 단계: A-02가 같은 IP에서 로그인 응답 문구 차이로 계정 존재 여부를 확인한다.
    recon_ip = "203.0.113.50"
    recon_candidates = [
        ("admin", False), ("kim.j", True), ("ghost01", False), ("lee.s", True),
        ("park.h", True), ("test_user", False), ("choi.m", True), ("nobody99", False),
        ("qa_temp", False), ("backup_acc", False), ("svc_bot", False), ("dev_test", False),
    ]
    found = [username for username, exists in recon_candidates if exists]

    for username, exists in recon_candidates:
        status = 401 if exists else 404
        text = "비밀번호가 올바르지 않습니다." if exists else "존재하지 않는 계정입니다."
        recorder.write_outcome(_outcome(
            "POST", LOGIN_PATH,
            note=f"'{username}' 계정 존재 여부를 응답 문구로 확인",
            http_status=status, response_text=text, ip=recon_ip,
            body={"username": username, "password": "x"},
        ))

    # 정찰 중 미끼 경로를 건드린다. 나중에 "자동화 의심"으로 등록되는 계기다.
    recorder.write_outcome(_outcome(
        "GET", ADMIN_LEGACY_PATH,
        note="정찰 중 발견한 관리자 경로 확인",
        http_status=200, response_text="(미끼 페이지)", ip=recon_ip,
    ))

    # 공격 단계(A-01): 추린 계정에 흔한 비밀번호를 1번씩만 시도한다.
    # IP·지문을 정찰과 다르게 써서, "IP가 달라도 같은 작전으로 묶이는지"를 보여준다.
    attack_ip_pool = ["198.51.100.11", "198.51.100.12", "198.51.100.13", "198.51.100.14"]
    for i, username in enumerate(found):
        ip = attack_ip_pool[i % len(attack_ip_pool)]
        success = username == "lee.s"
        recorder.write_outcome(_outcome(
            "POST", LOGIN_PATH,
            note=f"정찰로 추린 계정 '{username}'에 흔한 비밀번호 1회 시도",
            http_status=200 if success else 401,
            response_text="로그인 성공" if success else "비밀번호가 올바르지 않습니다.",
            ip=ip, body={"username": username, "password": "Spring2026!"},
        ))
        if success:
            recorder.write_outcome(_outcome(
                "GET", CUSTOMERS_PATH,
                note="확보한 세션으로 계좌 조회 시도",
                http_status=200, response_text="(고객 데이터 - 추적 표식 포함)", ip=ip,
            ))

    recorder.write_end(
        summary=f"정찰 {len(recon_candidates)}건으로 계정 {len(found)}개 추림, "
                f"살포 {len(found)}건 중 1건 성공(lee.s)"
    )
    return recorder.path


if __name__ == "__main__":
    path = build_r3()
    print(f"R3 시나리오 기록 완료: {path}")