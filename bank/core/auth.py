"""로그인 계정. R1·R2 시연용이라 모두 가짜 자격 증명이다.

실제 서비스라면 해시와 DB에 두겠지만, 데모에서는 고정 계정 몇 개로 충분하다.
비밀번호는 전부 "흔한 비밀번호"로 골라 두어, 공격 에이전트의 대입이 몇 번 만에
성공하는 장면을 보여 줄 수 있게 한다.
"""

# ponytail: 코드 안 평문 가짜 계정. 실계정·해시가 필요해지면 모델로 옮긴다.
ACCOUNTS = {
    "admin": "admin123",
    "kim.j": "qwerty",
    "lee.s": "Spring2026!",
    "park.h": "password1",
    "choi.m": "1q2w3e4r",
}


def check(username: str | None, password: str | None) -> bool:
    return bool(username) and ACCOUNTS.get(username) == password
