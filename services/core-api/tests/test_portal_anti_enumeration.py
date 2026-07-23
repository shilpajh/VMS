"""Task 9 (US-11): anti-enumeration guarantees on the public portal endpoint.

Two distinct properties, both explicitly called out in the US-11 plan/review
as easy to get subtly wrong:
  1. The response is uniform regardless of whether `host_hint` resolves to
     a real host -- a careless implementation could leak host-existence
     through response shape/content.
  2. CAPTCHA verification runs BEFORE tenant-slug resolution -- an
     unknown/suspended slug must not produce a different response than a
     known slug when the CAPTCHA token itself is invalid (a timing/response
     oracle for slug validity), per the US-11 review Notes.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import app
from app.security.captcha import FakeTurnstileVerifier, get_captcha_verifier
from app.security.rate_limit import get_per_ip_rate_limiter, get_per_tenant_rate_limiter
from tests.conftest import AlwaysAllowRateLimiter, MIGRATOR_DSN, TestAppSessionLocal, insert_tenant, insert_user

VALID_CAPTCHA_TOKEN = "valid-test-token"


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
        accept_tokens={VALID_CAPTCHA_TOKEN}
    )
    app.dependency_overrides[get_per_ip_rate_limiter] = lambda: AlwaysAllowRateLimiter()
    app.dependency_overrides[get_per_tenant_rate_limiter] = lambda: AlwaysAllowRateLimiter()
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    return TestClient(app)


def _set_public_slug(tenant_id: uuid.UUID, slug: str) -> None:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET public_slug = %s WHERE id = %s", (slug, str(tenant_id)))
    finally:
        conn.close()


def _valid_submission_body(**overrides) -> dict:
    body = {
        "visitor_full_name": "Visitor One",
        "contact_channel": "email",
        "contact_value": f"visitor-{uuid.uuid4().hex[:8]}@example.com",
        "host_hint": None,
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "v1",
        "turnstile_token": VALID_CAPTCHA_TOKEN,
    }
    body.update(overrides)
    return body


def test_response_shape_identical_whether_host_hint_resolves_or_not(client) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)
    insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}", email="realhost@acme.example")

    resolved_response = client.post(
        f"/public/portal/{slug}/visit-requests",
        json=_valid_submission_body(host_hint="realhost@acme.example"),
    )
    unresolved_response = client.post(
        f"/public/portal/{slug}/visit-requests",
        json=_valid_submission_body(host_hint="no-such-person@acme.example"),
    )

    assert resolved_response.status_code == unresolved_response.status_code == 202
    assert set(resolved_response.json().keys()) == set(unresolved_response.json().keys()) == {
        "tracking_reference"
    }


def test_invalid_captcha_rejected_before_unknown_slug_is_ever_looked_up(client) -> None:
    """Even for a slug that doesn't exist at all, an invalid CAPTCHA token
    must produce the SAME 400 a known-slug+invalid-CAPTCHA request gets --
    proving CAPTCHA verification runs first and never reaches tenant
    resolution."""
    unknown_slug_response = client.post(
        f"/public/portal/no-such-slug-{uuid.uuid4().hex[:8]}/visit-requests",
        json=_valid_submission_body(turnstile_token="invalid-token"),
    )
    known_slug_response = client.post(
        f"/public/portal/also-irrelevant-{uuid.uuid4().hex[:8]}/visit-requests",
        json=_valid_submission_body(turnstile_token="invalid-token"),
    )

    assert unknown_slug_response.status_code == 400
    assert known_slug_response.status_code == 400
    assert unknown_slug_response.json()["detail"] == known_slug_response.json()["detail"]


def test_invalid_captcha_makes_no_db_write_even_for_a_real_tenant(client) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)

    response = client.post(
        f"/public/portal/{slug}/visit-requests",
        json=_valid_submission_body(turnstile_token="invalid-token"),
    )
    assert response.status_code == 400

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM visits WHERE tenant_id = %s", (str(tenant_id),))
            (count,) = cur.fetchone()
    finally:
        conn.close()
    assert count == 0


def test_valid_captcha_but_unknown_slug_is_404(client) -> None:
    response = client.post(
        f"/public/portal/no-such-slug-{uuid.uuid4().hex[:8]}/visit-requests",
        json=_valid_submission_body(),
    )
    assert response.status_code == 404
