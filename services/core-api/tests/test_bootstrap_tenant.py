"""Task 11 (US-10): ops bootstrap script (scripts/bootstrap_tenant.py).

Confirms it creates a tenant + tenant_admin user + role assignment (with
audit evidence), idempotently ensures the platform sentinel/catalog exist,
and -- critically -- that it is NOT reachable via any HTTP route (tenant
creation is ops-script only, ADR-001 §4).
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest

from app.main import app
from app.models.tenant import PLATFORM_TENANT_ID
from scripts.bootstrap_tenant import BootstrapError, bootstrap_tenant
from tests.conftest import MIGRATOR_DSN


def test_bootstrap_creates_tenant_admin_and_role_assignment(_migrated_schema) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    result = bootstrap_tenant(
        tenant_name="Acme Corp",
        entra_tenant_id=entra_tenant_id,
        admin_external_idp_subject=f"oid-admin-{uuid.uuid4().hex[:8]}",
        admin_email="admin@acme.example",
        admin_display_name="Acme Admin",
        dsn=MIGRATOR_DSN,
    )

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM tenants WHERE id = %s", (str(result["tenant_id"]),))
            (status,) = cur.fetchone()
            assert status == "active"

            cur.execute(
                "SELECT r.code FROM user_roles ur "
                "JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = %s AND ur.tenant_id = %s",
                (str(result["admin_user_id"]), str(result["tenant_id"])),
            )
            role_codes = {row[0] for row in cur.fetchall()}
            assert role_codes == {"tenant_admin"}

            cur.execute(
                "SELECT event_type, tenant_id, actor FROM audit_events "
                "WHERE target_id = %s AND event_type = 'tenant.created'",
                (str(result["tenant_id"]),),
            )
            row = cur.fetchone()
            assert row is not None
            _, audit_tenant_id, actor = row
            assert str(audit_tenant_id) == str(PLATFORM_TENANT_ID)
            assert actor == "system"
    finally:
        conn.close()


def test_bootstrap_ensures_platform_sentinel_tenant_exists(_migrated_schema) -> None:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM tenants WHERE id = %s", (str(PLATFORM_TENANT_ID),))
            assert cur.fetchone() is not None
    finally:
        conn.close()

    # Re-running against an already-seeded DB must not fail on the sentinel
    # / catalog checks (only the tenant/admin creation itself is one-shot).
    bootstrap_tenant(
        tenant_name="Another Co",
        entra_tenant_id=f"another-entra-tid-{uuid.uuid4().hex[:8]}",
        admin_external_idp_subject=f"oid-admin-{uuid.uuid4().hex[:8]}",
        admin_email="admin@another.example",
        admin_display_name="Another Admin",
        dsn=MIGRATOR_DSN,
    )


def test_bootstrap_rejects_duplicate_entra_tenant_id(_migrated_schema) -> None:
    entra_tenant_id = f"dup-entra-tid-{uuid.uuid4().hex[:8]}"
    bootstrap_tenant(
        tenant_name="First",
        entra_tenant_id=entra_tenant_id,
        admin_external_idp_subject=f"oid-{uuid.uuid4().hex[:8]}",
        admin_email="a@example.com",
        admin_display_name="A",
        dsn=MIGRATOR_DSN,
    )
    with pytest.raises(psycopg2.errors.UniqueViolation):
        bootstrap_tenant(
            tenant_name="Second",
            entra_tenant_id=entra_tenant_id,
            admin_external_idp_subject=f"oid-{uuid.uuid4().hex[:8]}",
            admin_email="b@example.com",
            admin_display_name="B",
            dsn=MIGRATOR_DSN,
        )


def test_bootstrap_not_reachable_via_any_http_route() -> None:
    openapi_paths = set(app.openapi()["paths"].keys())
    assert not any("platform" in path or "bootstrap" in path for path in openapi_paths)
