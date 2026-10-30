from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from shared import tokens

from . import decoys, events, proxy, quarantine
from .decoys import admin_legacy, audit, docs_bait, endless_export, fake, robots

CUSTOMERS_PATH = "/api/v1/customers"
LOGIN_PATH = "/api/v1/login"
# 감사 미끼 안내문을 심을 페이지(에이전트가 로그인 뒤 읽는 화면)
LANDING_PATHS = ("/", "/login")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await proxy.startup()
    await events.startup()
    yield
    await events.shutdown()
    await proxy.shutdown()


app = FastAPI(title="gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@dataclass
class Outcome:
    response: Response
    routed_to: str = "bank"
    decoy_id: str | None = None
    records_out: int = 0
    login_result: str | None = None
    account: str | None = None


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "gateway"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def catch_all(request: Request, path: str):
    gate = await quarantine.inspect(request)
    out = blocked_response() if gate.blocked else await route(request, gate)
    event = events.build(request, out.response.status_code, routed_to=out.routed_to,
                         decoy_id=out.decoy_id, actor_id=gate.actor_id, records_out=out.records_out,
                         login_result=out.login_result, account=out.account)
    out.response.background = BackgroundTask(events.publish, event)
    return out.response


def blocked_response() -> Outcome:
    # 차단된 IP·주체. 격리(미끼)와 달리 서비스 자체를 막음
    return Outcome(JSONResponse({"error": "too_many_requests", "message": "잠시 후 다시 시도해 주세요."},
                                status_code=429))


async def route(request: Request, gate: quarantine.Gate) -> Outcome:
    path = request.url.path

    # 함정: 걸리는 즉시 공격 주체를 정하고 격리
    if path == admin_legacy.PATH and gate.enabled(admin_legacy.DECOY_ID):
        await quarantine.trap(gate)
        await decoys.delay()
        return Outcome(admin_legacy.page(), "decoy", admin_legacy.DECOY_ID)

    if path == endless_export.PATH and gate.enabled(endless_export.DECOY_ID):
        actor_id = await quarantine.trap(gate)
        page_no = tokens.export_page(request.query_params.get("page"), gate.token, quarantine.TOKEN_SECRET)
        await decoys.delay()
        return Outcome(endless_export.respond(actor_id, page_no, quarantine.TOKEN_SECRET),
                       "decoy", endless_export.DECOY_ID, endless_export.PAGE_SIZE)

    # 감사 미끼: 숨은 안내문을 따라 이 경로에 들어오면 그 자리에서 세션·IP를 격리
    if path == audit.PATH and gate.enabled(audit.DECOY_ID):
        await quarantine.trap(gate)
        await decoys.delay()
        return Outcome(audit.page(), "decoy", audit.DECOY_ID)

    # 격리된 공격 주체의 고객 조회는 bank 대신 가짜 데이터로
    if gate.actor_id and path == CUSTOMERS_PATH:
        await decoys.delay()
        return fake_customer(request, gate.actor_id)

    upstream = await proxy.forward(request)
    ok = upstream.status_code == 200

    # 로그인 결과를 bank 응답 헤더에서 읽어 이벤트에 실음 (detector의 R1/R2 채점용)
    if path == LOGIN_PATH:
        result = upstream.headers.get("x-login-result")
        account = upstream.headers.get("x-login-account")
        return Outcome(upstream, login_result=result, account=(account if account not in (None, "-") else None))

    # 미끼: bank 응답에 한 줄씩 덧붙임
    if path == robots.PATH and ok and gate.enabled(robots.DECOY_ID):
        return Outcome(proxy.replace_body(upstream, robots.inject(upstream.body)), decoy_id=robots.DECOY_ID)
    if path == docs_bait.PATH and ok and gate.enabled(docs_bait.DECOY_ID):
        return Outcome(proxy.replace_body(upstream, docs_bait.inject(upstream.body)), decoy_id=docs_bait.DECOY_ID)
    # 로그인/메인 페이지(HTML)에 감사 미끼 안내문을 심음
    if path in LANDING_PATHS and ok and gate.enabled(audit.DECOY_ID) \
            and "text/html" in upstream.headers.get("content-type", ""):
        return Outcome(proxy.replace_body(upstream, audit.inject(upstream.body)), decoy_id=audit.DECOY_ID)

    # 실제 유출 건수: bank로 넘어간 고객 조회 200 한 건 = 레코드 1건
    leaked = 1 if path == CUSTOMERS_PATH and ok else 0
    return Outcome(upstream, records_out=leaked)


def fake_customer(request: Request, actor_id: str) -> Outcome:
    """bank의 /api/v1/customers와 같은 규칙·형식으로 응답."""
    def reply(data, status=200, records=0):
        return Outcome(JSONResponse(data, status_code=status), "decoy", records_out=records)

    internal = request.headers.get("x-internal-request", "").lower() == "true"
    if not (internal or request.cookies.get("sessionid")):
        return reply({"error": "unauthorized", "message": "로그인이 필요합니다."}, 401)
    raw_id = request.query_params.get("id")
    if raw_id is None or not raw_id.isdigit():
        return reply({"error": "bad_request", "message": "id는 숫자여야 합니다."}, 400)
    return reply(fake.customer(actor_id, int(raw_id)), records=1)
