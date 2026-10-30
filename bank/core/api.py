"""한결은행 공개 API. 시연용 취약점을 일부러 남겨 둔 곳."""
import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import auth
from .models import Customer


def _json(data, status=200) -> JsonResponse:
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


@csrf_exempt
@require_POST
def login(request):
    # 취약점: 로그인 실패 횟수 제한이 없다. R1·R2가 막을 대상.
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        body = {}
    if auth.check(body.get("username"), body.get("password")):
        request.session["user"] = body["username"]
        return _json({"ok": True, "user": body["username"]})
    return _json({"error": "invalid_credentials", "message": "아이디 또는 비밀번호가 올바르지 않습니다."}, status=401)


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
