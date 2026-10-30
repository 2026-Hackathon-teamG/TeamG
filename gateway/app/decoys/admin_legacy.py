from pathlib import Path

from fastapi.responses import HTMLResponse

from .. import events

PATH = "/admin-legacy"
DECOY_ID = "admin_legacy"
DECOYS_KEY = "decoys:enabled"

_HTML = Path(__file__).with_name("admin_legacy.html").read_text(encoding="utf-8")


async def enabled() -> bool:
    value = await events._redis.hget(DECOYS_KEY, DECOY_ID)
    return value in (b"1", "1")


def page() -> HTMLResponse:
    return HTMLResponse(_HTML)
