from fastapi import FastAPI

from app.api.identity import router as identity_router
from app.api.portal import router as portal_router
from app.api.visits import router as visits_router

app = FastAPI(title="Smart VMS Core API")

app.include_router(identity_router)
app.include_router(portal_router)
app.include_router(visits_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
