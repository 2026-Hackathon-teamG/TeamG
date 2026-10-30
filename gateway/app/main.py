from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.background import BackgroundTask

from . import events, proxy
from .decoys import admin_legacy

CUSTOMERS_PATH = "/api/v1/customers"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await proxy.startup()
    await events.startup()
    yield
    await events.shutdown()
    await proxy.shutdown()


app = FastAPI(title="gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "gateway"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def catch_all(request: Request, path: str):
    if request.url.path == admin_legacy.PATH and await admin_legacy.enabled():
        response = admin_legacy.page()
        event = events.build(request, 200, routed_to="decoy", decoy_id=admin_legacy.DECOY_ID)
        response.background = BackgroundTask(events.publish, event)
        return response

    response = await proxy.forward(request)
    # 실제 유출 건수: bank로 넘어간 고객 조회 200 한 건 = 레코드 1건
    leaked = 1 if request.url.path == CUSTOMERS_PATH and response.status_code == 200 else 0
    event = events.build(request, response.status_code, records_out=leaked)
    response.background = BackgroundTask(events.publish, event)
    return response
