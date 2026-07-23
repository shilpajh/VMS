from fastapi import FastAPI

app = FastAPI(title="Smart VMS Core API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
