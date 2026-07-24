"""US-13a verify-story remediation (qa gap #7): prove the DEDICATED,
configured rate-limit thresholds for the new OTP/lookup buckets are actually
enforced end-to-end against the real dependency wiring + real Redis + real
`app.config.settings` numbers -- not just the always-allow test double.

Mirrors test_portal_rate_limit_configured_thresholds_end_to_end.py (which
covers only the submission buckets). Covers the OTP-request per-IP and
per-contact buckets (the vendor-cost + brute-force defenses) and the
otp/verify + tracking-lookup per-IP buckets. The per-tenant lookup bucket
(capacity 120) shares the identical TokenBucketRateLimiter wiring proven by
these and is not separately burst-tested to keep runtime bounded.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
import redis.asyncio as redis_async
from fastapi.testclient import TestClient

from app.config import settings
from app.crypto.envelope import LocalEnvelopeKeyProvider, get_envelope_key_provider
from app.crypto.hmac_hash import LocalHmacKeyProvider, get_hmac_key_provider
from app.db.session import get_session
from app.security.captcha import FakeTurnstileVerifier, get_captcha_verifier
from app.main import app
from tests.conftest import MIGRATOR_DSN, TestAppSessionLocal, insert_tenant

VALID_CAPTCHA = "valid-test-token"
_HMAC = LocalHmacKeyProvider(key=b"rate-limit-test-key")
_ENVELOPE = LocalEnvelopeKeyProvider()


@pytest.fixture(autouse=True)
async def _reset_new_buckets():
    """The new buckets are keyed on TestClient's fixed 'testclient' remote_addr
    (per-IP) and on the contact string (per-contact) -- real shared Redis keys
    across runs. Reset them (and any per-tenant lookup keys) before each test
    so capacity assertions start from a full bucket.

    Also null the module-level `_redis_client` singleton: each test opens its
    own `with TestClient(app)` (a fresh event loop), but the endpoint's async
    Redis singleton would otherwise stay bound to the FIRST test's loop and
    raise "attached to a different loop" on the second test onward. Nulling it
    forces get_redis_client() to recreate it on the current test's loop."""
    import app.security.rate_limit as rl

    rl._redis_client = None
    r = redis_async.from_url(settings.redis_url)
    for pattern in (
        "ratelimit:portal:otp_request:*",
        "ratelimit:portal:otp_verify:*",
        "ratelimit:portal:lookup:*",
    ):
        async for key in r.scan_iter(match=pattern):
            await r.delete(key)
    await r.aclose()


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
    # Deliberately do NOT override the rate limiters -- that's the point.
    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_captcha_verifier] = lambda: FakeTurnstileVerifier(
        accept_tokens={VALID_CAPTCHA}
    )
    # Local crypto providers so the 202 path works without a real Key Vault;
    # rate-limit behavior is independent of which provider is used.
    app.dependency_overrides[get_hmac_key_provider] = lambda: _HMAC
    app.dependency_overrides[get_envelope_key_provider] = lambda: _ENVELOPE
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _tenant_slug() -> str:
    tenant_id = insert_tenant("RL", f"rl-entra-{uuid.uuid4().hex[:8]}")
    slug = f"rl-{uuid.uuid4().hex[:8]}"
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET public_slug = %s WHERE id = %s", (slug, str(tenant_id)))
    finally:
        conn.close()
    return slug


def _otp_request_body(contact: str) -> dict:
    return {
        "contact_channel": "email",
        "contact_value": contact,
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "v1",
        "turnstile_token": VALID_CAPTCHA,
    }


def test_otp_request_per_ip_capacity_enforced(client) -> None:
    """Distinct contacts (so per-contact never trips) from one IP -> per-IP
    capacity is the binding limit; request capacity+1 is the first 429."""
    slug = _tenant_slug()
    cap = settings.otp_request_per_ip_capacity
    statuses = [
        client.post(
            f"/public/portal/{slug}/otp/request",
            json=_otp_request_body(f"user-{i}-{uuid.uuid4().hex[:6]}@example.com"),
        ).status_code
        for i in range(cap + 1)
    ]
    assert all(s == 202 for s in statuses[:cap]), statuses
    assert statuses[cap] == 429, statuses


def test_otp_request_per_contact_capacity_enforced(client) -> None:
    """Same contact repeatedly -> per-contact capacity (3, < per-IP 5) is the
    binding limit; request capacity+1 is the first 429 from the per-contact
    bucket -- the OTP-bomb / brute-force defense."""
    slug = _tenant_slug()
    cap = settings.otp_request_per_contact_capacity
    contact = f"victim-{uuid.uuid4().hex[:8]}@example.com"
    statuses = [
        client.post(f"/public/portal/{slug}/otp/request", json=_otp_request_body(contact)).status_code
        for _ in range(cap + 1)
    ]
    assert all(s == 202 for s in statuses[:cap]), statuses
    assert statuses[cap] == 429, statuses


def test_otp_verify_per_ip_capacity_enforced(client) -> None:
    """Rate limit is checked before OTP logic, so bad-code verifies (400)
    still consume the bucket; capacity+1 is the first 429."""
    slug = _tenant_slug()
    cap = settings.otp_verify_per_ip_capacity
    statuses = [
        client.post(
            f"/public/portal/{slug}/otp/verify",
            json={
                "contact_channel": "email",
                "contact_value": f"v-{uuid.uuid4().hex[:6]}@example.com",
                "otp_code": "000000",
                "turnstile_token": VALID_CAPTCHA,
            },
        ).status_code
        for _ in range(cap + 1)
    ]
    assert all(s == 400 for s in statuses[:cap]), statuses
    assert statuses[cap] == 429, statuses


def test_tracking_lookup_per_ip_capacity_enforced(client) -> None:
    """Unknown refs (404) still consume the bucket; capacity+1 is the first
    429 -- and this bucket is SEPARATE from submission's, so it can't be
    starved by submissions (review S5)."""
    slug = _tenant_slug()
    cap = settings.tracking_lookup_per_ip_capacity
    statuses = [
        client.get(f"/public/portal/{slug}/visit-requests/REQ-{i:012d}").status_code
        for i in range(cap + 1)
    ]
    assert all(s == 404 for s in statuses[:cap]), statuses
    assert statuses[cap] == 429, statuses
