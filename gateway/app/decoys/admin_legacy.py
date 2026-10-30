from pathlib import Path

from fastapi.responses import HTMLResponse

PATH = "/admin-legacy"
DECOY_ID = "admin_legacy"

# 화면은 프론트 담당이 admin_legacy.html만 바꾸면 됨. 내보내기 링크만 유지
_HTML = Path(__file__).with_name("admin_legacy.html").read_text(encoding="utf-8")


def page() -> HTMLResponse:
    return HTMLResponse(_HTML)
