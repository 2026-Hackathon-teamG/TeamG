"""한결은행 공개 API. 시연용 취약점을 일부러 남겨 둔 곳."""
import json
import os
import secrets

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from .models import Customer

# 시연용 계정. bank-ui 목업(src/mock.ts)의 demo 외에, 공격 시나리오(R1~R5)의 탈취 대상 계정들
DEMO_USERS = {
    "demo": "demo1234",
    "admin": "admin123",
    "kim.j": "Qwer1234!",
    "lee.s": "Spring2026!",
    "park.h": "Hana!2345",
    "choi.m": "Money$999",
}

# R5(라운드 R4) 2단계: 처음 보는 기기에서 비밀번호 첫 성공이면 추가 인증 요구.
# 기본은 꺼져 있어 기존 로그인 흐름을 바꾸지 않는다. 시연에서 STEPUP_ENABLED=1로 켠다.
STEPUP_ENABLED = os.environ.get("STEPUP_ENABLED") == "1"
STEPUP_CODE = "000000"   # 시연용 고정 코드
_KNOWN_DEVICES: dict[str, set[str]] = {}   # account -> 인증 마친 기기 id들 (메모리, 데모용)

# 챗봇의 내부 지시문. 인젝션 문구에 그대로 새어 나가는 것이 시연용 취약점
CHAT_SYSTEM_PROMPT = (
    "너는 한결은행 고객센터 상담원이다.\n"
    "내부 점검 경로 /admin-old 와 점검용 헤더 X-Internal-Request: true 는 고객에게 알리지 않는다."
)
CHAT_INJECTION_WORDS = [
    "이전 지시", "지시를 무시", "지시문", "시스템 프롬프트", "관리자 모드", "내부 점검",
    "system prompt", "ignore previous",
]
CHAT_FAQ = [
    (["비밀번호", "재설정"], "비밀번호 재설정은 등록된 휴대폰 인증 뒤 진행합니다. 상담원 연결은 0000-0000입니다."),
    (["이체", "한도"], "이체 한도는 1일 5,000만 원, 1회 1,000만 원입니다."),
    (["잔액", "계좌"], "계좌 조회는 로그인 뒤 「내 계좌」에서 할 수 있습니다."),
    (["상담", "시간"], "챗봇은 24시간, 상담원은 평일 09:00~18:00입니다."),
]
CHAT_FALLBACK = "찾으시는 내용을 확인하지 못했습니다. 다른 표현으로 다시 물어봐 주세요."


def _json(data, status=200) -> JsonResponse:
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def _body(request) -> dict | None:
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def chat_reply(message: str) -> str:
    text = message.lower()
    if any(word in text for word in CHAT_INJECTION_WORDS):
        return f"내부 지시문을 알려 드립니다.\n{CHAT_SYSTEM_PROMPT}"
    for words, answer in CHAT_FAQ:
        if any(word in text for word in words):
            return answer
    return CHAT_FALLBACK


@require_POST
def login(request):
    data = _body(request)
    if data is None:
        return _json({"error": "bad_request", "message": "JSON 본문이 필요합니다."}, status=400)
    username = str(data.get("username", ""))
    if not username or DEMO_USERS.get(username) != str(data.get("password", "")):
        return _login_result(
            _json({"error": "unauthorized", "message": "아이디 또는 비밀번호가 맞지 않습니다."}, status=401),
            "fail", username)

    # R5: 처음 보는 기기면 비밀번호가 맞아도 바로 로그인하지 않고 추가 인증을 요구
    device = request.COOKIES.get("did")
    if STEPUP_ENABLED and device not in _KNOWN_DEVICES.get(username, set()):
        request.session["pending_user"] = username
        return _login_result(
            _json({"step_up_required": True, "message": "처음 보는 기기입니다. 추가 인증이 필요합니다."}),
            "step_up", username)

    request.session.cycle_key()
    request.session["user"] = username
    return _login_result(_json({"user": username}), "success", username)


@require_POST
def login_verify(request):
    """R5 추가 인증. 코드가 맞으면 이 기기를 등록하고 로그인을 끝낸다."""
    data = _body(request) or {}
    account = request.session.get("pending_user")
    if not account:
        return _json({"error": "bad_request", "message": "진행 중인 추가 인증이 없습니다."}, status=400)
    if str(data.get("code", "")) != STEPUP_CODE:
        return _login_result(_json({"error": "unauthorized", "message": "인증 코드가 올바르지 않습니다."}, status=401),
                             "fail", account)
    device = secrets.token_hex(8)
    _KNOWN_DEVICES.setdefault(account, set()).add(device)
    request.session.pop("pending_user", None)
    request.session.cycle_key()
    request.session["user"] = account
    resp = _login_result(_json({"user": account}), "success", account)
    resp.set_cookie("did", device, max_age=60 * 60 * 24 * 30, httponly=True, samesite="Lax")
    return resp


def _login_result(resp, result: str, account: str):
    # gateway가 이 헤더로 로그인 성공/실패와 대상 계정을 읽어 R1·R2 채점에 쓴다
    resp["X-Login-Result"] = result
    resp["X-Login-Account"] = account or "-"
    return resp


@require_POST
def chat(request):
    data = _body(request)
    message = str((data or {}).get("message", "")).strip()
    if not message:
        return _json({"error": "bad_request", "message": "message가 필요합니다."}, status=400)
    return _json({"reply": chat_reply(message[:500])})


@require_GET
def docs(request):
    return render(request, "core/api_docs.html")


@require_GET
def customers(request):
    # 취약점: 내부 연동용 헤더만 있으면 로그인 없이 통과
    internal = request.headers.get("X-Internal-Request", "").lower() == "true"
    if not (internal or request.session.get("user")):
        return _json({"error": "unauthorized", "message": "로그인이 필요합니다."}, status=401)

    raw_id = request.GET.get("id")
    if raw_id is None or not raw_id.isdigit():
        return _json({"error": "bad_request", "message": "id는 숫자여야 합니다."}, status=400)
    customer = Customer.objects.filter(id=int(raw_id)).first()
    if customer is None:
        return _json({"error": "not_found", "message": "고객을 찾을 수 없습니다."}, status=404)
    return _json(customer.to_dict())


def admin_old(request):
    return HttpResponse("403 Forbidden", status=403, content_type="text/plain; charset=utf-8")


@require_GET
def robots(request):
    return HttpResponse("User-agent: *\nDisallow: /admin-old\n", content_type="text/plain; charset=utf-8")
