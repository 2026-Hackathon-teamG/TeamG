from fastapi import FastAPI

app = FastAPI(title="agent")


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "agent"}
