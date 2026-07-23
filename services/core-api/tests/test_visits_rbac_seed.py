"""Task 1 (US-11): tenants.public_slug uniqueness + view_visits RBAC seed
(0002_visits_and_outbox). Extends the US-10 RBAC test pattern
(tests/test_rbac.py) for the new permission only -- does not re-test the
full US-10 matrix.
"""

from __future__ import annotations

import uuid

import psycopg2
import psycopg2.errors
import pytest

from app.domain.rbac import PERMISSION_POLICY_VERSION, get_user_permissions, has_permission
from tests.conftest import MIGRATOR_DSN, assign_role, insert_tenant, insert_user, set_tenant_context


def test_permission_policy_version_bumped_to_v2() -> None:
    assert PERMISSION_POLICY_VERSION == "v2"


def _insert_tenant_with_slug(name: str, entra_tenant_id: str, public_slug: str | None) -> uuid.UUID:
    """Tenant creation is ops-script only (ADR-001 §4) -- vms_app has no
    INSERT grant on `tenants`. Mirrors tests/conftest.py's insert_tenant
    helper (MIGRATOR_DSN/BYPASSRLS), extended with public_slug."""
    tenant_id = uuid.uuid4()
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (id, name, entra_tenant_id, public_slug, status) "
                "VALUES (%s, %s, %s, %s, 'active')",
                (str(tenant_id), name, entra_tenant_id, public_slug),
            )
    finally:
        conn.close()
    return tenant_id


def test_public_slug_is_unique() -> None:
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _insert_tenant_with_slug("Acme", f"acme-entra-{uuid.uuid4().hex[:8]}", slug)

    with pytest.raises(psycopg2.errors.UniqueViolation):
        _insert_tenant_with_slug("Acme Duplicate", f"acme2-entra-{uuid.uuid4().hex[:8]}", slug)


def test_public_slug_defaults_to_null_and_is_optional() -> None:
    tenant_id = _insert_tenant_with_slug(
        "NoSlug", f"noslug-entra-{uuid.uuid4().hex[:8]}", None
    )  # must not raise -- public_slug is nullable

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT public_slug FROM tenants WHERE id = %s", (str(tenant_id),))
            (public_slug,) = cur.fetchone()
    finally:
        conn.close()
    assert public_slug is None


def _fetch_tenant_public_slug_column_exists() -> bool:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'tenants' AND column_name = 'public_slug'"
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def test_tenants_public_slug_column_exists_after_migration() -> None:
    assert _fetch_tenant_public_slug_column_exists()


@pytest.fixture()
def tenant_id():
    return insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")


async def test_reception_security_and_tenant_admin_resolve_view_visits_true(
    app_session, tenant_id
) -> None:
    reception_user = insert_user(tenant_id, f"oid-reception-{uuid.uuid4().hex[:8]}")
    assign_role(tenant_id, reception_user, "reception_security")

    admin_user = insert_user(tenant_id, f"oid-admin-{uuid.uuid4().hex[:8]}")
    assign_role(tenant_id, admin_user, "tenant_admin")

    await set_tenant_context(app_session, tenant_id)

    assert await has_permission(app_session, tenant_id, reception_user, "view_visits") is True
    assert await has_permission(app_session, tenant_id, admin_user, "view_visits") is True


async def test_host_does_not_resolve_view_visits(app_session, tenant_id) -> None:
    host_user = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    assign_role(tenant_id, host_user, "host")

    await set_tenant_context(app_session, tenant_id)

    assert await has_permission(app_session, tenant_id, host_user, "view_visits") is False


async def test_reception_security_still_has_prior_us10_permissions(app_session, tenant_id) -> None:
    """The view_visits addition is additive -- it must not regress the
    existing US-10 seed for the same role."""
    reception_user = insert_user(tenant_id, f"oid-reception2-{uuid.uuid4().hex[:8]}")
    assign_role(tenant_id, reception_user, "reception_security")

    await set_tenant_context(app_session, tenant_id)
    permissions = await get_user_permissions(app_session, tenant_id, reception_user)

    assert permissions == {"approve_deny_holds", "checkin_confirm", "view_visits"}
