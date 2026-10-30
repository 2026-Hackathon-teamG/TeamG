from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from . import proxy


@asynccontextmanager
async def lifespan(app: FastAPI):
    await proxy.startup()
    yield
    await proxy.shutdown()


app = FastAPI(title="gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "gateway"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def catch_all(request: Request, path: str):
    return await proxy.forward(request)
