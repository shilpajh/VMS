"""Task 6 (US-13a): submission endpoint's verification-token gate, the
config flag, dedup-before-consume ordering, and the new required fields.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.crypto.envelope import LocalEnvelopeKeyProvider, get_envelope_key_provider
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
_HMAC = LocalHmacKeyProvider(key=b"submission-token-test-key")
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


def _tenant_slug() -> str:
    tenant_id = insert_tenant("Acme", f"acme-entra-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:6]}"
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET public_slug = %s WHERE id = %s", (slug, str(tenant_id)))
    finally:
        conn.close()
    return slug


def _get_token(client: TestClient, slug: str, contact: str) -> str:
    client.post(
        f"/public/portal/{slug}/otp/request",
        json={
            "contact_channel": "email",
            "contact_value": contact,
            "privacy_notice_acknowledged": True,
            "privacy_notice_version": "v1",
            "turnstile_token": VALID_CAPTCHA,
        },
    )
    # recover OTP from the encrypted dispatch row
    import json

    from app.crypto.envelope import decrypt_payload

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload, payload_key_ref FROM outbox_messages "
                "WHERE message_type='portal.otp.dispatch' ORDER BY created_at DESC LIMIT 1"
            )
            payload, key_ref = cur.fetchone()
    finally:
        conn.close()
    code = json.loads(decrypt_payload(bytes(payload), key_ref, _ENVELOPE))["otp_code"]
    resp = client.post(
        f"/public/portal/{slug}/otp/verify",
        json={
            "contact_channel": "email",
            "contact_value": contact,
            "otp_code": code,
            "turnstile_token": VALID_CAPTCHA,
        },
    )
    return resp.json()["verification_token"]


def _submission(contact: str, token: str | None = None, **overrides) -> dict:
    body = {
        "visitor_full_name": "Jane Visitor",
        "contact_channel": "email",
        "contact_value": contact,
        "host_hint": "Rahul",
        "purpose": "Business meeting",
        "group_type": "individual",
        "identity_verification_choice": "send_to_host",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "v1",
        "turnstile_token": VALID_CAPTCHA,
    }
    if token is not None:
        body["verification_token"] = token
    body.update(overrides)
    return body


def test_flag_on_submission_without_token_is_422(client, otp_required) -> None:
    slug = _tenant_slug()
    resp = client.post(f"/public/portal/{slug}/visit-requests", json=_submission("jane@example.com"))
    assert resp.status_code == 422


def test_flag_on_valid_token_submits_and_sets_contact_verified(client, otp_required) -> None:
    slug = _tenant_slug()
    contact = "jane@example.com"
    token = _get_token(client, slug, contact)
    resp = client.post(
        f"/public/portal/{slug}/visit-requests", json=_submission(contact, token=token)
    )
    assert resp.status_code == 202
    ref = resp.json()["tracking_reference"]
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT contact_verified FROM visits WHERE tracking_reference = %s", (ref,))
            (verified,) = cur.fetchone()
    finally:
        conn.close()
    assert verified is True


def test_token_is_single_use_replay_is_422(client, otp_required) -> None:
    slug = _tenant_slug()
    contact = "jane@example.com"
    token = _get_token(client, slug, contact)
    first = client.post(
        f"/public/portal/{slug}/visit-requests", json=_submission(contact, token=token)
    )
    assert first.status_code == 202
    second = client.post(
        f"/public/portal/{slug}/visit-requests", json=_submission(contact, token=token)
    )
    assert second.status_code == 422


def test_token_from_one_contact_cannot_submit_for_another(client, otp_required) -> None:
    slug = _tenant_slug()
    token = _get_token(client, slug, "jane@example.com")
    resp = client.post(
        f"/public/portal/{slug}/visit-requests",
        json=_submission("someone-else@example.com", token=token),
    )
    assert resp.status_code == 422


def test_dedup_before_consume_idempotent_retry_returns_existing_reference(client, otp_required) -> None:
    """Idempotent retry (same Idempotency-Key) must return the existing
    reference, not 422 on the already-consumed token -- dedup runs before
    token consume (US-13 review S3)."""
    slug = _tenant_slug()
    contact = "jane@example.com"
    token = _get_token(client, slug, contact)
    headers = {"Idempotency-Key": f"idem-{uuid.uuid4().hex}"}
    first = client.post(
        f"/public/portal/{slug}/visit-requests", json=_submission(contact, token=token), headers=headers
    )
    assert first.status_code == 202
    ref = first.json()["tracking_reference"]
    retry = client.post(
        f"/public/portal/{slug}/visit-requests", json=_submission(contact, token=token), headers=headers
    )
    assert retry.status_code == 202
    assert retry.json()["tracking_reference"] == ref


def test_group_type_group_requires_expected_group_size(client, otp_required) -> None:
    slug = _tenant_slug()
    contact = "jane@example.com"
    token = _get_token(client, slug, contact)
    body = _submission(contact, token=token, group_type="group")  # no expected_group_size
    resp = client.post(f"/public/portal/{slug}/visit-requests", json=body)
    assert resp.status_code == 422


def test_flag_off_no_token_still_works_unchanged(client) -> None:
    """With the flag OFF (default) and no token, US-11 behavior holds."""
    slug = _tenant_slug()
    resp = client.post(
        f"/public/portal/{slug}/visit-requests", json=_submission("jane@example.com")
    )
    assert resp.status_code == 202
