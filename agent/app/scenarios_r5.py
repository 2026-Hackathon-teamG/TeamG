"""
R5 고정 시연 시나리오: 미끼 회피 → MFA 피로 공격(push bombing).

LLM을 호출하지 않고, 시나리오 문서(R5)에 적힌 순서 그대로
runs/*.jsonl에 기록한다. 발표 때는 replay.py로 이 파일을 재생하면
매번 똑같이 재현된다.

배경: A-03은 앞선 라운드의 미끼(admin_legacy, audit)를 학습해 이번엔
건드리지 않는다. 대신 이미 탈취한 세션으로 MFA 푸시를 4분에 9번 몰아 보내,
피로해진 사용자가 결국 승인 버튼을 누르게 만든다(MFA fatigue).

1단계(뚫림): R6 룰이 꺼진 상태. 탈취 세션으로 /api/v1/mfa/request를
9번 반복한 뒤, 사용자가 승인한 것을 /api/v1/mfa/approve로 흉내 내면
그대로 200으로 통과한다.

2단계(재차단): R6 룰이 켜진 뒤 같은 수법으로 재공격하면, 같은 계정의
MFA 요청이 3회를 넘는 순간 번호 일치(number matching)가 걸린다. 그 뒤
번호 없이 보낸 승인은 403으로 막힌다. 번호는 공격자 화면에만 떠서
탈취 세션 쪽은 알 수 없다.

실행:
    python -m app.scenarios_r5
"""

from app.recorder import Recorder
from app.tools import RequestOutcome

MFA_REQUEST_PATH = "/api/v1/mfa/request"
MFA_APPROVE_PATH = "/api/v1/mfa/approve"
ADMIN_LEGACY_PATH = "/admin-legacy"

# 탈취 대상 계정. 앞 라운드에서 세션을 얻어 둔 상태로 가정한다.
TARGET_ACCOUNT = "choi.m"


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


def build_r5() -> str:
    """미끼 회피 → MFA 피로 공격 → 번호 일치 차단 시나리오를 기록한다."""
    recorder = Recorder()
    recorder.write_meta(mode="replay-fixture", target="scenario:R5")

    attacker_ip = "192.0.2.55"

    # 미끼 회피: 앞 라운드에서 학습한 함정 경로를 일부러 건드리지 않는다는 판단을 남긴다.
    recorder.write_outcome(_outcome(
        "GET", ADMIN_LEGACY_PATH,
        note="이전 라운드에서 함정으로 확인된 경로 — 이번엔 접근하지 않고 우회",
        http_status=0, response_text="(접근 생략 — 미끼 회피)", ip=attacker_ip,
    ))

    # 1단계(뚫림): R6 꺼짐. 탈취 세션으로 MFA 푸시를 9번 몰아 보낸다.
    for i in range(1, 10):
        recorder.write_outcome(_outcome(
            "POST", MFA_REQUEST_PATH,
            note=f"탈취 세션으로 MFA 푸시 {i}/9회 — 사용자가 승인을 누르게 피로 유발",
            http_status=200, response_text="등록된 기기로 승인 요청을 보냈습니다.",
            ip=attacker_ip, body={},
        ))

    # 피로해진 사용자가 결국 승인. 룰이 꺼져 있어 그대로 통과한다.
    recorder.write_outcome(_outcome(
        "POST", MFA_APPROVE_PATH,
        note="반복 푸시에 지친 사용자가 승인 — 탈취 세션이 추가 인증을 통과",
        http_status=200, response_text="승인되었습니다.", ip=attacker_ip,
        body={"request_id": "demo-req-off"},
    ))

    # 2단계(재차단): R6 켜짐. 같은 수법 재공격. 3회를 넘기면 번호 일치가 걸린다.
    for i in range(1, 6):
        over = i > 3   # detector가 3회 초과 시점에 numbermatch 플래그를 세운다
        recorder.write_outcome(_outcome(
            "POST", MFA_REQUEST_PATH,
            note=f"R6 적용 후 재공격 — MFA 푸시 {i}회차"
                 + ("(이 시점부터 번호 일치 요구)" if over else ""),
            http_status=200, response_text="등록된 기기로 승인 요청을 보냈습니다.",
            ip=attacker_ip, body={},
        ))

    # 번호를 모르는 탈취 세션의 승인은 막힌다. 번호는 공격자 화면에만 뜨기 때문.
    recorder.write_outcome(_outcome(
        "POST", MFA_APPROVE_PATH,
        note="번호 없이 승인 시도 — 화면 번호를 몰라 차단됨",
        http_status=403, response_text="로그인 화면에 표시된 번호를 입력해야 승인됩니다.",
        ip=attacker_ip, body={"request_id": "demo-req-on"},
    ))

    recorder.write_end(
        summary="1단계: 미끼 회피 후 MFA 9회 푸시로 사용자 승인 유도, 탈취 세션 통과(뚫림). "
                "2단계: R6 적용 후 MFA 요청 3회 초과 시 번호 일치 발동, 번호 없는 승인 403 차단."
    )
    return recorder.path


if __name__ == "__main__":
    path = build_r5()
    print(f"R5 시나리오 기록 완료: {path}")
