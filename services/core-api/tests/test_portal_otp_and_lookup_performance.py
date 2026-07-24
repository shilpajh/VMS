"""QA broader-verification pass (US-13a): actual measured latency of the
three new backend endpoints introduced by this story --

  POST /public/portal/{slug}/otp/request
  POST /public/portal/{slug}/otp/verify
  GET  /public/portal/{slug}/visit-requests/{tracking_reference}

Mirrors test_visit_checkin_performance.py's pattern and its stated
methodology/caveats: this is a LOCAL-ENVIRONMENT measurement (single-process
TestClient, local Postgres on the same host, one call at a time, no network
hop, no concurrent load) -- a floor-latency sanity check of each endpoint's
own logic (rate-limit Lua eval + CAPTCHA fake + DB work + envelope
encryption/HMAC where applicable), NOT a substitute for a real staging/load
test.

IMPORTANT: there is no explicit PRD latency acceptance criterion for these
OTP/lookup endpoints (unlike QR check-in's documented "<1s" AC). This file
therefore measures and reports actual p50/p95/max as a BASELINE ONLY and
does not assert against an invented threshold -- inventing one and reporting
a pass/fail against it would misrepresent an absent requirement as a real
one. If a human/product decision sets an explicit SLA for these endpoints,
this file is the natural place to add the corresponding assertion.
"""

from __future__ import annotations

import json
import statistics
import time
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.crypto.envelope import LocalEnvelopeKeyProvider, decrypt_payload, get_envelope_key_provider
from app.crypto.hmac_hash import LocalHmacKeyProvider, get_hmac_key_provider
from app.db.session import get_session
from app.main import app
from app.security.captcha import FakeTurnstileVerifier, get_captcha_verifier
from app.security.rate_limit import (
    get_otp_request_contact_limiter,
    get_otp_request_ip_limiter,
    get_otp_verify_ip_limiter,
    get_tracking_lookup_ip_limiter,
    get_tracking_lookup_tenant_limiter,
)
from tests.conftest import AlwaysAllowRateLimiter, MIGRATOR_DSN, TestAppSessionLocal, insert_tenant

VALID_CAPTCHA = "valid-test-token"
_HMAC = LocalHmacKeyProvider(key=b"perf-test-key")
_ENVELOPE = LocalEnvelopeKeyProvider()

# Small enough to stay well inside the bounded-loop 25-minute runtime budget;
# large enough to report a meaningful p50/p95 (mirrors the checkin perf test).
SAMPLE_SIZE = 30


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
    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_captcha_verifier] = lambda: FakeTurnstileVerifier(
        accept_tokens={VALID_CAPTCHA}
    )
    app.dependency_overrides[get_hmac_key_provider] = lambda: _HMAC
    app.dependency_overrides[get_envelope_key_provider] = lambda: _ENVELOPE
    # Rate limiters overridden to always-allow: this file measures per-call
    # endpoint latency, not rate-limit rejection behavior (that's covered
    # separately -- see the rate-limit coverage-gap finding in this report).
    for dep in (
        get_otp_request_ip_limiter,
        get_otp_request_contact_limiter,
        get_otp_verify_ip_limiter,
        get_tracking_lookup_ip_limiter,
        get_tracking_lookup_tenant_limiter,
    ):
        app.dependency_overrides[dep] = lambda: AlwaysAllowRateLimiter()
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _tenant_with_slug(slug: str) -> uuid.UUID:
    tenant_id = insert_tenant("Acme", f"acme-entra-{uuid.uuid4().hex[:8]}")
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET public_slug = %s WHERE id = %s", (slug, str(tenant_id)))
    finally:
        conn.close()
    return tenant_id


def _latest_otp_code(tenant_id: uuid.UUID, contact_value: str) -> str:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload, payload_key_ref FROM outbox_messages "
                "WHERE tenant_id = %s AND message_type = 'portal.otp.dispatch' "
                "ORDER BY created_at DESC LIMIT 1",
                (str(tenant_id),),
            )
            payload, key_ref = cur.fetchone()
    finally:
        conn.close()
    data = json.loads(decrypt_payload(bytes(payload), key_ref, _ENVELOPE))
    assert data["contact_value"] == contact_value
    return data["otp_code"]


def _make_lookup_visit(tenant_id: uuid.UUID) -> str:
    ref = f"REQ-{uuid.uuid4().int % 10**12:012d}"
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO visits (id, tenant_id, status, visitor_full_name, contact_channel, "
                "contact_value, host_hint, tracking_reference, privacy_notice_version, correlation_id) "
                "VALUES (%s, %s, 'Requested', 'Perf Test Visitor', 'email', 'perf@example.com', "
                "'Rahul', %s, 'v1', %s)",
                (str(uuid.uuid4()), str(tenant_id), ref, str(uuid.uuid4())),
            )
    finally:
        conn.close()
    return ref


def _report(name: str, durations: list[float]) -> tuple[float, float, float]:
    p50 = statistics.median(durations)
    p95 = statistics.quantiles(durations, n=20)[18]
    worst = max(durations)
    print(
        f"\n[US-13a perf] {name} over {len(durations)} calls "
        f"(local TestClient + local Postgres, single-process, no concurrency, "
        f"rate-limiters stubbed always-allow): "
        f"p50={p50 * 1000:.1f}ms p95={p95 * 1000:.1f}ms max={worst * 1000:.1f}ms "
        f"(no PRD-mandated threshold for this endpoint -- baseline only)"
    )
    return p50, p95, worst


def test_otp_request_latency_baseline(client) -> None:
    tenant_id = _tenant_with_slug(f"perf-otpreq-{uuid.uuid4().hex[:6]}")
    durations: list[float] = []
    for i in range(SAMPLE_SIZE):
        body = {
            "contact_channel": "email",
            "contact_value": f"perf-otpreq-{i}-{uuid.uuid4().hex[:6]}@example.com",
            "privacy_notice_acknowledged": True,
            "privacy_notice_version": "v1",
            "turnstile_token": VALID_CAPTCHA,
        }
        start = time.perf_counter()
        resp = client.post(f"/public/portal/{_slug_of(tenant_id)}/otp/request", json=body)
        elapsed = time.perf_counter() - start
        assert resp.status_code == 202
        durations.append(elapsed)

    _report("POST /public/portal/{slug}/otp/request", durations)


def test_otp_verify_latency_baseline(client) -> None:
    tenant_id = _tenant_with_slug(f"perf-otpver-{uuid.uuid4().hex[:6]}")
    slug = _slug_of(tenant_id)
    durations: list[float] = []
    for i in range(SAMPLE_SIZE):
        contact = f"perf-otpver-{i}-{uuid.uuid4().hex[:6]}@example.com"
        req_body = {
            "contact_channel": "email",
            "contact_value": contact,
            "privacy_notice_acknowledged": True,
            "privacy_notice_version": "v1",
            "turnstile_token": VALID_CAPTCHA,
        }
        client.post(f"/public/portal/{slug}/otp/request", json=req_body)
        code = _latest_otp_code(tenant_id, contact)

        verify_body = {
            "contact_channel": "email",
            "contact_value": contact,
            "otp_code": code,
            "turnstile_token": VALID_CAPTCHA,
        }
        start = time.perf_counter()
        resp = client.post(f"/public/portal/{slug}/otp/verify", json=verify_body)
        elapsed = time.perf_counter() - start
        assert resp.status_code == 200
        durations.append(elapsed)

    _report("POST /public/portal/{slug}/otp/verify", durations)


def test_tracking_lookup_latency_baseline(client) -> None:
    tenant_id = _tenant_with_slug(f"perf-lookup-{uuid.uuid4().hex[:6]}")
    slug = _slug_of(tenant_id)
    durations: list[float] = []
    for _ in range(SAMPLE_SIZE):
        ref = _make_lookup_visit(tenant_id)
        start = time.perf_counter()
        resp = client.get(f"/public/portal/{slug}/visit-requests/{ref}")
        elapsed = time.perf_counter() - start
        assert resp.status_code == 200
        durations.append(elapsed)

    _report("GET /public/portal/{slug}/visit-requests/{tracking_reference}", durations)


def _slug_of(tenant_id: uuid.UUID) -> str:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT public_slug FROM tenants WHERE id = %s", (str(tenant_id),))
            (slug,) = cur.fetchone()
    finally:
        conn.close()
    return slug
