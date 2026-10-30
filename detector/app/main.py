from fastapi import FastAPI

app = FastAPI(title="detector")


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "detector"}
