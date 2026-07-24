from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.identity import router as identity_router
from app.api.portal import router as portal_router
from app.api.visits import router as visits_router
from app.config import settings

app = FastAPI(title="Smart VMS Core API")

# Browser-facing CORS -- explicit allowlist (never "*"), since staff routes
# carry an Authorization bearer header and credentialed requests. Local dev
# default is the Vite dev server only (app/config.py); real deployments set
# this via real app configuration, never checked in. (US-13b re-applies the
# US-01 fix that was orphaned before its PR.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(identity_router)
app.include_router(portal_router)
app.include_router(visits_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
