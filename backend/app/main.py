from fastapi import FastAPI

app = FastAPI(title="RoadTrace AI", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}
