"""US-13b task 1: CORS middleware (re-applied from US-01, which was orphaned
before the US-01 PR). Without it, the browser (Vite dev origin :5173) cannot
reach the API (:8000) at all -- every portal fetch is blocked. curl/TestClient
bypass CORS (browser-only policy), so this test explicitly asserts the
response carries the Access-Control-Allow-Origin header for an allowed origin.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_allowed_origin_gets_cors_headers() -> None:
    origin = settings.cors_allowed_origins[0]
    resp = client.get("/health", headers={"Origin": origin})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin


def test_preflight_options_is_allowed_for_a_portal_route() -> None:
    origin = settings.cors_allowed_origins[0]
    resp = client.options(
        "/public/portal/acme/visit-requests",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == origin


def test_cors_allowlist_is_not_wildcard() -> None:
    """Staff routes carry an Authorization bearer header -> credentialed
    requests -> the allowlist must be explicit origins, never '*'."""
    assert "*" not in settings.cors_allowed_origins
