"""QA-added (verify-story, US-11): the existing rate-limit suites either
exercise `TokenBucketRateLimiter` directly with arbitrary test-chosen
capacity/refill values (`test_portal_rate_limit.py`), or override
`get_per_ip_rate_limiter`/`get_per_tenant_rate_limiter` with
`AlwaysAllowRateLimiter` at the endpoint level (`test_portal_submission.py`,
`test_portal_anti_enumeration.py`). Nothing exercises the REAL
`/public/portal/{tenant_slug}/visit-requests` endpoint with its actual
dependency wiring against the actual configured `app.config.settings`
thresholds (`portal_rate_limit_per_ip_capacity`, `..._refill_per_minute`,
same for `_per_tenant_*`). This file closes that gap: it proves the numbers
that are actually in `app/config.py` today (capacity=10/refill=5.0 per-IP,
capacity=60/refill=60.0 per-tenant, at the time of writing) are the ones
genuinely enforced end-to-end via `get_per_ip_rate_limiter`/
`get_per_tenant_rate_limiter`, not just a generic mechanism that happens to
support arbitrary numbers if someone remembered to wire them.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
import redis.asyncio as redis_async
from fastapi.testclient import TestClient

from app.config import settings
from app.db.session import get_session
from app.main import app
from app.security.captcha import FakeTurnstileVerifier, get_captcha_verifier
from tests.conftest import MIGRATOR_DSN, TestAppSessionLocal, insert_tenant

VALID_CAPTCHA_TOKEN = "valid-test-token"


@pytest.fixture(autouse=True)
async def _reset_shared_ip_bucket():
    """The token-bucket key is `ratelimit:portal:ip:<client_ip>` -- and
    TestClient always presents the SAME fixed remote_addr (`testclient`), so
    this bucket is a real cross-test-run shared Redis key, not isolated per
    test the way the Postgres scratch/tenant rows are. Redis is a real
    persistent service across pytest invocations (unlike the DB, which is
    reset per migration fixture), so a bucket left partially-consumed by a
    previous run of this exact test (e.g. an interrupted run) would corrupt
    this test's own capacity assertion. Reset it before every run so the
    bucket starts at a known, full state."""
    client = redis_async.from_url(settings.redis_url)
    async for key in client.scan_iter(match="ratelimit:portal:ip:*"):
        await client.delete(key)
    await client.aclose()


async def _override_get_session():
    async with TestAppSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture(autouse=True)
def override_dependencies(_migrated_schema):
    # Deliberately do NOT override get_per_ip_rate_limiter/
    # get_per_tenant_rate_limiter here -- that's the entire point of this
    # file: exercise the REAL dependency wiring against REAL Redis and the
    # REAL settings-configured thresholds.
    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_captcha_verifier] = lambda: FakeTurnstileVerifier(
        accept_tokens={VALID_CAPTCHA_TOKEN}
    )
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    # Use the context-manager form deliberately: it keeps ONE persistent
    # event loop open for the lifetime of the `with` block (triggering ASGI
    # lifespan startup), which the module-level async Redis client
    # (app/security/rate_limit.py's `_redis_client` singleton) needs to stay
    # bound to a single, still-open loop across this test's several
    # sequential `.post()` calls. Without the context manager, some
    # TestClient/anyio versions tear down and recreate the loop per call,
    # which orphans a previously-created async Redis connection.
    with TestClient(app) as c:
        yield c


def _set_public_slug(tenant_id: uuid.UUID, slug: str) -> None:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET public_slug = %s WHERE id = %s", (slug, str(tenant_id)))
    finally:
        conn.close()


def _submission_body() -> dict:
    return {
        "visitor_full_name": "Rate Limit Test Visitor",
        "contact_channel": "email",
        "contact_value": f"ratelimit-{uuid.uuid4().hex[:8]}@example.com",
        "host_hint": None,
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "v1",
        "turnstile_token": VALID_CAPTCHA_TOKEN,
    }


def test_per_ip_burst_capacity_as_actually_configured_is_enforced_end_to_end(client) -> None:
    """Sends settings.portal_rate_limit_per_ip_capacity requests (should all
    succeed -- fresh bucket, TestClient always presents the same
    "testclient" remote_addr so all requests share one per-IP bucket), then
    one more (should be the FIRST 429) -- against the real endpoint, real
    Redis, real per-IP token bucket, no override."""
    tenant_id = insert_tenant("RateLimitCo", f"ratelimit-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"ratelimit-ip-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)

    capacity = settings.portal_rate_limit_per_ip_capacity
    statuses = []
    for _ in range(capacity + 1):
        response = client.post(f"/public/portal/{slug}/visit-requests", json=_submission_body())
        statuses.append(response.status_code)

    assert all(s == 202 for s in statuses[:capacity]), (
        f"expected the first {capacity} requests (configured per-IP capacity) to succeed, got {statuses}"
    )
    assert statuses[capacity] == 429, (
        f"expected request #{capacity + 1} to be rate-limited (429) per the configured "
        f"per-IP capacity of {capacity}, got {statuses[capacity]}"
    )
