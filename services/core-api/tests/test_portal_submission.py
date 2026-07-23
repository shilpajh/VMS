"""Task 9 (US-11): public portal submission endpoint (app/api/portal.py).

Gherkin Scenario 1 ("Portal submission is visible immediately as
Requested"). Exercises the full HTTP surface via FastAPI's TestClient, with
CAPTCHA/session/rate-limit dependencies overridden -- never a real Cloudflare
call, never the dev DB default.
"""

from __future__ import annotations

import re
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import app
from app.models import AuditEvent, Visit
from app.security.captcha import FakeTurnstileVerifier, get_captcha_verifier
from app.security.rate_limit import get_per_ip_rate_limiter, get_per_tenant_rate_limiter
from tests.conftest import (
    AlwaysAllowRateLimiter,
    MIGRATOR_DSN,
    TestAppSessionLocal,
    insert_tenant,
    insert_user,
)

TRACKING_REFERENCE_PATTERN = re.compile(r"^REQ-\d+$")
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


def _fetch_visit(visit_id: uuid.UUID) -> dict:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, host_user_id, tracking_reference, correlation_id "
                "FROM visits WHERE id = %s",
                (str(visit_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return row


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


def test_submission_creates_requested_visit_and_returns_tracking_reference(client) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)

    host_oid = f"oid-host-{uuid.uuid4().hex[:8]}"
    insert_user(tenant_id, host_oid, email="rahul@acme.example", display_name="rahul@acme")

    response = client.post(
        f"/public/portal/{slug}/visit-requests",
        json=_valid_submission_body(host_hint="rahul@acme"),
    )

    assert response.status_code == 202
    body = response.json()
    assert TRACKING_REFERENCE_PATTERN.match(body["tracking_reference"])
    assert set(body.keys()) == {"tracking_reference"}  # no host/other data leaked

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, host_user_id FROM visits WHERE tenant_id = %s "
                "AND tracking_reference = %s",
                (str(tenant_id), body["tracking_reference"]),
            )
            status_, host_user_id = cur.fetchone()
    finally:
        conn.close()
    assert status_ == "Requested"
    assert host_user_id is not None  # resolved via exact email match


def test_unresolved_host_hint_still_creates_visit_with_null_host(client) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)

    response = client.post(
        f"/public/portal/{slug}/visit-requests",
        json=_valid_submission_body(host_hint="no-such-host@acme.example"),
    )

    assert response.status_code == 202
    tracking_reference = response.json()["tracking_reference"]

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT host_user_id FROM visits WHERE tenant_id = %s AND tracking_reference = %s",
                (str(tenant_id), tracking_reference),
            )
            (host_user_id,) = cur.fetchone()
    finally:
        conn.close()
    assert host_user_id is None


def test_missing_privacy_notice_acknowledgment_is_422_no_visit_created(client) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)

    response = client.post(
        f"/public/portal/{slug}/visit-requests",
        json=_valid_submission_body(privacy_notice_acknowledged=False),
    )

    assert response.status_code == 422

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM visits WHERE tenant_id = %s", (str(tenant_id),))
            (count,) = cur.fetchone()
    finally:
        conn.close()
    assert count == 0


def test_visit_requested_audit_written_with_portal_actor_and_correlation_id(client) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)

    response = client.post(
        f"/public/portal/{slug}/visit-requests", json=_valid_submission_body()
    )
    assert response.status_code == 202

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT actor, correlation_id, target_type, target_id FROM audit_events "
                "WHERE tenant_id = %s AND event_type = 'visit.requested'",
                (str(tenant_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None
    actor, correlation_id, target_type, target_id = row
    assert actor == "portal"
    assert correlation_id is not None
    assert target_type == "visit"


def test_idempotency_key_dedup_returns_same_tracking_reference(client) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)

    body = _valid_submission_body(host_hint="same-host@acme.example")
    headers = {"Idempotency-Key": "client-supplied-key-123"}

    first = client.post(f"/public/portal/{slug}/visit-requests", json=body, headers=headers)
    second = client.post(f"/public/portal/{slug}/visit-requests", json=body, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["tracking_reference"] == second.json()["tracking_reference"]

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM visits WHERE tenant_id = %s AND contact_value = %s",
                (str(tenant_id), body["contact_value"]),
            )
            (count,) = cur.fetchone()
    finally:
        conn.close()
    assert count == 1  # deduped -- exactly one visit row


def test_idempotency_key_dedup_is_content_hashed_not_raw_client_key(client) -> None:
    """The SAME literal Idempotency-Key header value, reused across two
    DIFFERENT submissions (different contact_value/host_hint), must NOT
    dedup them together -- proving the dedup key is derived from submission
    content, not trusted directly from the client-supplied header value
    (US-11 review, Should-fix #1)."""
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)

    headers = {"Idempotency-Key": "reused-client-key"}
    first_body = _valid_submission_body(host_hint="host-a@acme.example")
    second_body = _valid_submission_body(host_hint="host-b@acme.example")

    first = client.post(f"/public/portal/{slug}/visit-requests", json=first_body, headers=headers)
    second = client.post(f"/public/portal/{slug}/visit-requests", json=second_body, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["tracking_reference"] != second.json()["tracking_reference"]


def test_idempotency_dedup_is_scoped_per_tenant(client) -> None:
    """The same content + same Idempotency-Key submitted to two DIFFERENT
    tenants must create two independent visits, never leaking one tenant's
    tracking reference to another (US-11 review, Should-fix #1: tenant-scoped
    dedup)."""
    tenant_a = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    tenant_b = insert_tenant("Globex", f"globex-entra-tid-{uuid.uuid4().hex[:8]}")
    slug_a = f"acme-{uuid.uuid4().hex[:8]}"
    slug_b = f"globex-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_a, slug_a)
    _set_public_slug(tenant_b, slug_b)

    body = _valid_submission_body(host_hint="same-host@example.com")
    headers = {"Idempotency-Key": "same-key-both-tenants"}

    response_a = client.post(f"/public/portal/{slug_a}/visit-requests", json=body, headers=headers)
    response_b = client.post(f"/public/portal/{slug_b}/visit-requests", json=body, headers=headers)

    assert response_a.status_code == 202
    assert response_b.status_code == 202
    assert response_a.json()["tracking_reference"] != response_b.json()["tracking_reference"]


def test_no_idempotency_key_header_never_dedups(client) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)

    body = _valid_submission_body()
    first = client.post(f"/public/portal/{slug}/visit-requests", json=body)
    second = client.post(f"/public/portal/{slug}/visit-requests", json=body)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["tracking_reference"] != second.json()["tracking_reference"]
