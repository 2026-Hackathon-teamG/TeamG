import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db, stream, worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.startup()
    task = asyncio.create_task(worker.run())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await db.shutdown()


app = FastAPI(title="detector", lifespan=lifespan)
app.include_router(stream.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "detector"}
