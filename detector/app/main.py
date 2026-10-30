import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, ops, rds, worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.startup()
    await rds.startup()
    await ops.sync_decoys_to_redis(await db.list_decoys())
    task = asyncio.create_task(worker.run())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await rds.shutdown()
    await db.shutdown()


app = FastAPI(title="detector", lifespan=lifespan)
# ops-ui(:8003)에서 호출
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(ops.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "detector"}
