"""
안전장치(assert_target_is_safe) 최소 테스트.

CLAUDE.md 규칙: "공격 에이전트는 이 레포의 로컬 gateway만 대상으로 합니다"를
코드가 실제로 지키는지 확인한다. 리뷰에서 지적된 버그
(gateway를 막아버리는 것)가 다시 생기면 이 테스트가 바로 잡아낸다.

실행:
    cd agent
    pytest tests/test_safety.py
"""

import pytest

from app.config import assert_target_is_safe


def test_localhost_allowed():
    """로컬에서 compose 없이 직접 돌릴 때 쓰는 호스트."""
    assert_target_is_safe("http://localhost:8000")


def test_127_0_0_1_allowed():
    assert_target_is_safe("http://127.0.0.1:8000")


def test_gateway_allowed():
    """compose 내부에서 서비스명으로 접근하는 경우. 이전 버전의 버그였던 지점."""
    assert_target_is_safe("http://gateway:8000")


def test_external_host_blocked():
    """로컬/compose 내부가 아닌 대상은 반드시 막아야 한다."""
    with pytest.raises(RuntimeError):
        assert_target_is_safe("https://example.com")


def test_real_looking_bank_host_blocked():
    """실제 은행처럼 보이는 외부 호스트도 당연히 막혀야 한다."""
    with pytest.raises(RuntimeError):
        assert_target_is_safe("https://api.realbank.example.com")