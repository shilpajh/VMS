"""Task 7 (US-13a): GET /public/portal/{slug}/visit-requests/{ref}.

Returns status + the visitor's OWN submitted details only -- never the
resolved employee host name, never a check-in code (decision 2 / review B2).
Uniform 404 across unknown / wrong-tenant / malformed (anti-enumeration).
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import app
from app.security.rate_limit import (
    get_tracking_lookup_ip_limiter,
    get_tracking_lookup_tenant_limiter,
)
from tests.conftest import AlwaysAllowRateLimiter, MIGRATOR_DSN, TestAppSessionLocal, insert_tenant, insert_user


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
    app.dependency_overrides[get_tracking_lookup_ip_limiter] = lambda: AlwaysAllowRateLimiter()
    app.dependency_overrides[get_tracking_lookup_tenant_limiter] = lambda: AlwaysAllowRateLimiter()
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


def _make_visit(tenant_id: uuid.UUID, *, host_hint: str | None, host_user_id: uuid.UUID | None,
                status_: str = "Requested") -> str:
    ref = f"REQ-{uuid.uuid4().int % 10**12:012d}"
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO visits (id, tenant_id, status, visitor_full_name, contact_channel, "
                "contact_value, host_hint, host_user_id, tracking_reference, "
                "privacy_notice_version, correlation_id) "
                "VALUES (%s, %s, %s, 'Jane Visitor', 'email', 'jane@example.com', %s, %s, %s, 'v1', %s)",
                (str(uuid.uuid4()), str(tenant_id), status_, host_hint,
                 str(host_user_id) if host_user_id else None, ref, str(uuid.uuid4())),
            )
    finally:
        conn.close()
    return ref


def test_lookup_returns_status_and_own_details(client) -> None:
    tenant_id = _tenant_with_slug(f"acme-{uuid.uuid4().hex[:6]}")
    slug = _slug_of(tenant_id)
    ref = _make_visit(tenant_id, host_hint="Rahul", host_user_id=None)
    resp = client.get(f"/public/portal/{slug}/visit-requests/{ref}")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "Requested", "visitor_full_name": "Jane Visitor", "host_hint": "Rahul"}


def test_lookup_never_leaks_resolved_employee_name(client) -> None:
    """Even when host_hint resolved to a real employee, the response shows
    the visitor's TYPED host_hint, never the employee's display_name."""
    tenant_id = _tenant_with_slug(f"acme-{uuid.uuid4().hex[:6]}")
    slug = _slug_of(tenant_id)
    host_id = insert_user(tenant_id, f"oid-{uuid.uuid4().hex[:8]}", email="rahul@acme.example",
                          display_name="Rahul Mehta")
    ref = _make_visit(tenant_id, host_hint="rahul@acme.example", host_user_id=host_id)
    resp = client.get(f"/public/portal/{slug}/visit-requests/{ref}")
    assert resp.status_code == 200
    assert "Rahul Mehta" not in resp.text  # resolved employee name never leaks
    assert resp.json()["host_hint"] == "rahul@acme.example"  # only the typed string


def test_lookup_never_returns_a_checkin_code(client) -> None:
    tenant_id = _tenant_with_slug(f"acme-{uuid.uuid4().hex[:6]}")
    slug = _slug_of(tenant_id)
    ref = _make_visit(tenant_id, host_hint="Rahul", host_user_id=None, status_="Registered")
    resp = client.get(f"/public/portal/{slug}/visit-requests/{ref}")
    assert resp.status_code == 200
    assert "checkin_code" not in resp.text
    assert set(resp.json().keys()) == {"status", "visitor_full_name", "host_hint"}


def test_lookup_unknown_and_wrong_tenant_and_malformed_are_byte_identical_404(client) -> None:
    tenant_a = _tenant_with_slug(f"acme-{uuid.uuid4().hex[:6]}")
    slug_a = _slug_of(tenant_a)
    tenant_b = _tenant_with_slug(f"globex-{uuid.uuid4().hex[:6]}")
    slug_b = _slug_of(tenant_b)
    real_ref_in_b = _make_visit(tenant_b, host_hint="X", host_user_id=None)

    unknown = client.get(f"/public/portal/{slug_a}/visit-requests/REQ-000000000000")
    cross_tenant = client.get(f"/public/portal/{slug_a}/visit-requests/{real_ref_in_b}")
    malformed = client.get(f"/public/portal/{slug_a}/visit-requests/not-a-ref")

    assert unknown.status_code == cross_tenant.status_code == malformed.status_code == 404
    assert unknown.json() == cross_tenant.json() == malformed.json()


def _slug_of(tenant_id: uuid.UUID) -> str:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT public_slug FROM tenants WHERE id = %s", (str(tenant_id),))
            (slug,) = cur.fetchone()
    finally:
        conn.close()
    return slug
