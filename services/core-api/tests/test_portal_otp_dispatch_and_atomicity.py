"""US-13a verify-story remediation: close the qa-pass coverage gaps.

- #6: portal.otp.dispatch outbox idempotency key is deterministic + unique
  per verification row (mirrors test_visit_approval_outbox.py's precedent,
  the `tests.md` mandatory idempotency suite).
- #5: a rejected submission (bad verification token, OTP required) creates
  ZERO visits and leaves no partial state -- the one-transaction-per-request
  atomicity property, asserted at the DB, not just via the 422 status.
"""

from __future__ import annotations

import json
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.api.portal import otp_dispatch_idempotency_key
from app.crypto.envelope import LocalEnvelopeKeyProvider, decrypt_payload, get_envelope_key_provider
from app.crypto.hmac_hash import LocalHmacKeyProvider, get_hmac_key_provider
from app.db.session import get_session
from app.main import app
from app.security.captcha import FakeTurnstileVerifier, get_captcha_verifier
from app.security.rate_limit import (
    get_otp_request_contact_limiter,
    get_otp_request_ip_limiter,
    get_otp_verify_ip_limiter,
    get_per_ip_rate_limiter,
    get_per_tenant_rate_limiter,
)
from tests.conftest import AlwaysAllowRateLimiter, MIGRATOR_DSN, TestAppSessionLocal, insert_tenant

VALID_CAPTCHA = "valid-test-token"
_HMAC = LocalHmacKeyProvider(key=b"dispatch-atomicity-test-key")
_ENVELOPE = LocalEnvelopeKeyProvider()


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
    for dep in (
        get_per_ip_rate_limiter,
        get_per_tenant_rate_limiter,
        get_otp_request_ip_limiter,
        get_otp_request_contact_limiter,
        get_otp_verify_ip_limiter,
    ):
        app.dependency_overrides[dep] = lambda: AlwaysAllowRateLimiter()
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def otp_required(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "portal_otp_required", True)
    yield


def _tenant_slug() -> tuple[uuid.UUID, str]:
    tenant_id = insert_tenant("Acme", f"acme-entra-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:6]}"
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET public_slug = %s WHERE id = %s", (slug, str(tenant_id)))
    finally:
        conn.close()
    return tenant_id, slug


def _otp_request(client, slug, contact="jane@example.com"):
    return client.post(
        f"/public/portal/{slug}/otp/request",
        json={
            "contact_channel": "email",
            "contact_value": contact,
            "privacy_notice_acknowledged": True,
            "privacy_notice_version": "v1",
            "turnstile_token": VALID_CAPTCHA,
        },
    )


# --- #6: dispatch idempotency key ---

def test_otp_dispatch_row_has_deterministic_unique_idempotency_key(client) -> None:
    tenant_id, slug = _tenant_slug()
    _otp_request(client, slug)
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT aggregate_id, aggregate_type, idempotency_key, not_valid_after, payload "
                "FROM outbox_messages WHERE tenant_id = %s AND message_type = 'portal.otp.dispatch'",
                (str(tenant_id),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    aggregate_id, aggregate_type, idem_key, not_valid_after, payload = rows[0]
    assert aggregate_type == "portal_contact_verification"
    assert idem_key == otp_dispatch_idempotency_key(uuid.UUID(str(aggregate_id)))
    assert not_valid_after is not None  # = otp_expires_at, drives the send-gate
    # payload is ciphertext, not cleartext
    assert b"jane@example.com" not in bytes(payload)


def test_resend_produces_a_distinct_dispatch_row_and_key(client) -> None:
    """A legitimate resend re-dispatches: a fresh verification row (new UUID)
    -> a distinct idempotency key -> a second outbox row (ADR-004 §4). The
    UNIQUE constraint on idempotency_key never collides because the key is
    per-row, not per-contact."""
    tenant_id, slug = _tenant_slug()
    _otp_request(client, slug)
    _otp_request(client, slug)  # resend
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT idempotency_key FROM outbox_messages "
                "WHERE tenant_id = %s AND message_type = 'portal.otp.dispatch'",
                (str(tenant_id),),
            )
            keys = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    assert len(keys) == 2
    assert keys[0] != keys[1]  # distinct per verification row


# --- #5: rejected-submission atomicity ---

def test_rejected_submission_creates_zero_visits(client, otp_required) -> None:
    tenant_id, slug = _tenant_slug()
    body = {
        "visitor_full_name": "Jane Visitor",
        "contact_channel": "email",
        "contact_value": "jane@example.com",
        "host_hint": "Rahul",
        "purpose": "Business meeting",
        "group_type": "individual",
        "identity_verification_choice": "send_to_host",
        "verification_token": "a-bogus-never-issued-token",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "v1",
        "turnstile_token": VALID_CAPTCHA,
    }
    resp = client.post(f"/public/portal/{slug}/visit-requests", json=body)
    assert resp.status_code == 422
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM visits WHERE tenant_id = %s AND contact_value = 'jane@example.com'",
                (str(tenant_id),),
            )
            (n,) = cur.fetchone()
    finally:
        conn.close()
    assert n == 0  # no partial state from a rejected submission
