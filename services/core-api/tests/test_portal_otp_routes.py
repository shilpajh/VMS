"""Task 5 (US-13a): POST /public/portal/{slug}/otp/request and /otp/verify.

Full HTTP surface via TestClient with CAPTCHA / rate-limit / HMAC / envelope
dependencies overridden -- never a real Cloudflare/Key Vault call.
"""

from __future__ import annotations

import json
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
)
from tests.conftest import AlwaysAllowRateLimiter, MIGRATOR_DSN, TestAppSessionLocal, insert_tenant

VALID_CAPTCHA = "valid-test-token"
_HMAC = LocalHmacKeyProvider(key=b"otp-route-test-key")
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
    app.dependency_overrides[get_otp_request_ip_limiter] = lambda: AlwaysAllowRateLimiter()
    app.dependency_overrides[get_otp_request_contact_limiter] = lambda: AlwaysAllowRateLimiter()
    app.dependency_overrides[get_otp_verify_ip_limiter] = lambda: AlwaysAllowRateLimiter()
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    return TestClient(app)


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


def _latest_otp_dispatch_code(tenant_id: uuid.UUID, contact_value: str) -> str:
    """Demo-only: recover the plaintext OTP by decrypting the dispatch outbox
    row (as US-01's demo recovered the check-in code)."""
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT o.payload, o.payload_key_ref FROM outbox_messages o "
                "WHERE o.tenant_id = %s AND o.message_type = 'portal.otp.dispatch' "
                "ORDER BY o.created_at DESC LIMIT 1",
                (str(tenant_id),),
            )
            payload, key_ref = cur.fetchone()
    finally:
        conn.close()
    data = json.loads(decrypt_payload(bytes(payload), key_ref, _ENVELOPE))
    assert data["contact_value"] == contact_value
    return data["otp_code"]


def _otp_request_body(contact="jane@example.com", ack=True):
    return {
        "contact_channel": "email",
        "contact_value": contact,
        "privacy_notice_acknowledged": ack,
        "privacy_notice_version": "v1",
        "turnstile_token": VALID_CAPTCHA,
    }


# --- otp/request ---

def test_request_otp_returns_generic_202_and_writes_encrypted_dispatch(client) -> None:
    tenant_id = _tenant_with_slug(f"acme-{uuid.uuid4().hex[:6]}")
    slug = _slug_of(tenant_id)
    resp = client.post(f"/public/portal/{slug}/otp/request", json=_otp_request_body())
    assert resp.status_code == 202
    # dispatch row exists, encrypted, recoverable
    code = _latest_otp_dispatch_code(tenant_id, "jane@example.com")
    assert len(code) == 6 and code.isdigit()


def test_request_otp_without_consent_is_422(client) -> None:
    tenant_id = _tenant_with_slug(f"acme-{uuid.uuid4().hex[:6]}")
    slug = _slug_of(tenant_id)
    resp = client.post(f"/public/portal/{slug}/otp/request", json=_otp_request_body(ack=False))
    assert resp.status_code == 422


def test_request_otp_bad_captcha_is_400_no_dispatch(client) -> None:
    tenant_id = _tenant_with_slug(f"acme-{uuid.uuid4().hex[:6]}")
    slug = _slug_of(tenant_id)
    body = _otp_request_body()
    body["turnstile_token"] = "wrong"
    resp = client.post(f"/public/portal/{slug}/otp/request", json=body)
    assert resp.status_code == 400
    # no dispatch row written
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM outbox_messages WHERE tenant_id = %s "
                "AND message_type = 'portal.otp.dispatch'",
                (str(tenant_id),),
            )
            (n,) = cur.fetchone()
    finally:
        conn.close()
    assert n == 0


def test_request_otp_unknown_slug_is_uniform_404(client) -> None:
    resp = client.post("/public/portal/no-such-slug/otp/request", json=_otp_request_body())
    assert resp.status_code == 404


# --- otp/verify ---

def test_verify_correct_code_returns_token(client) -> None:
    tenant_id = _tenant_with_slug(f"acme-{uuid.uuid4().hex[:6]}")
    slug = _slug_of(tenant_id)
    client.post(f"/public/portal/{slug}/otp/request", json=_otp_request_body())
    code = _latest_otp_dispatch_code(tenant_id, "jane@example.com")

    resp = client.post(
        f"/public/portal/{slug}/otp/verify",
        json={
            "contact_channel": "email",
            "contact_value": "jane@example.com",
            "otp_code": code,
            "turnstile_token": VALID_CAPTCHA,
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["verification_token"]) > 20


def test_verify_wrong_code_is_uniform_400(client) -> None:
    tenant_id = _tenant_with_slug(f"acme-{uuid.uuid4().hex[:6]}")
    slug = _slug_of(tenant_id)
    client.post(f"/public/portal/{slug}/otp/request", json=_otp_request_body())
    resp = client.post(
        f"/public/portal/{slug}/otp/verify",
        json={
            "contact_channel": "email",
            "contact_value": "jane@example.com",
            "otp_code": "999999",
            "turnstile_token": VALID_CAPTCHA,
        },
    )
    assert resp.status_code == 400


def test_verify_no_pending_otp_same_uniform_400(client) -> None:
    tenant_id = _tenant_with_slug(f"acme-{uuid.uuid4().hex[:6]}")
    slug = _slug_of(tenant_id)
    resp = client.post(
        f"/public/portal/{slug}/otp/verify",
        json={
            "contact_channel": "email",
            "contact_value": "never@example.com",
            "otp_code": "123456",
            "turnstile_token": VALID_CAPTCHA,
        },
    )
    assert resp.status_code == 400


def _slug_of(tenant_id: uuid.UUID) -> str:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT public_slug FROM tenants WHERE id = %s", (str(tenant_id),))
            (slug,) = cur.fetchone()
    finally:
        conn.close()
    return slug
