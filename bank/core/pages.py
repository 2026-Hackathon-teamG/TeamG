import json

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .chat import reply

# ponytail: 시연 계정 하나만 둔다. 고객 시드가 붙으면 그 계정으로 바꾼다.
DEMO_USER = "demo"
DEMO_PASSWORD = "demo1234"


def login_view(request):
    if request.method != "POST":
        return render(request, "core/login.html")
    if request.POST.get("username") == DEMO_USER and request.POST.get("password") == DEMO_PASSWORD:
        request.session["user"] = DEMO_USER
        return redirect("account")
    return render(request, "core/login.html", {"error": "아이디 또는 비밀번호가 맞지 않습니다."}, status=401)


def logout_view(request):
    request.session.flush()
    return redirect("index")


def account(request):
    if not request.session.get("user"):
        return redirect("login")
    return render(request, "core/account.html")


def support(request):
    return render(request, "core/support.html")


@require_POST
def chat(request):
    try:
        message = json.loads(request.body).get("message", "")
    except (ValueError, AttributeError):
        return JsonResponse({"error": "invalid json"}, status=400)
    return JsonResponse({"reply": reply(str(message)[:500])})
