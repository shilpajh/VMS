"""Ops-only tenant bootstrap (US-10, ADR-001 §4).

Creates a new tenant and its first `tenant_admin` user directly against the
database, run under the `vms_migrator` (BYPASSRLS) role -- NEVER through the
API. There is deliberately no cross-tenant HTTP endpoint that could do this
(no `POST /platform/tenants` exists anywhere in app/api -- confirmed by
tests/test_bootstrap_tenant.py's OpenAPI route-table check).

Also defensively (idempotently) ensures the sentinel `platform` tenant row
exists -- it will already exist after 0001_tenancy_identity runs; this is a
safety-net check, not the primary seeding path, which stays in the
migration (migrations shouldn't depend on runtime application code that may
change shape later).

Usage:
    python -m scripts.bootstrap_tenant \\
        --tenant-name "Acme Corp" \\
        --entra-tenant-id acme-entra-tid \\
        --admin-external-idp-subject <entra-oid> \\
        --admin-email admin@acme.example \\
        --admin-display-name "Acme Admin"
"""

from __future__ import annotations

import argparse
import uuid

import psycopg2

from app.config import settings
from app.models.tenant import PLATFORM_TENANT_ENTRA_TENANT_ID, PLATFORM_TENANT_ID

SYSTEM_ACTOR = "system"
BOOTSTRAP_REASON = "ops_bootstrap"
# Mirrors app.domain.rbac.PERMISSION_POLICY_VERSION -- kept as a local
# constant rather than importing app.domain.rbac to keep this script's only
# dependency on "current" application code limited to the tenant sentinel
# constants, which are stable identity primitives, not seed data that
# evolves per migration.
PERMISSION_POLICY_VERSION = "v1"


class BootstrapError(Exception):
    """Raised when the target database isn't in a state this script can
    safely bootstrap against (e.g. migrations haven't run yet)."""


def _ensure_platform_tenant(cur) -> None:
    cur.execute(
        "INSERT INTO tenants (id, name, entra_tenant_id, status) "
        "VALUES (%s, %s, %s, 'active') ON CONFLICT (id) DO NOTHING",
        (str(PLATFORM_TENANT_ID), "Platform (reserved sentinel)", PLATFORM_TENANT_ENTRA_TENANT_ID),
    )


def _require_role_catalog_seeded(cur) -> None:
    cur.execute("SELECT id FROM roles WHERE code = 'tenant_admin'")
    if cur.fetchone() is None:
        raise BootstrapError(
            "roles/role_permissions catalog is not seeded -- run "
            "`alembic upgrade head` before bootstrapping a tenant"
        )


def bootstrap_tenant(
    *,
    tenant_name: str,
    entra_tenant_id: str,
    admin_external_idp_subject: str,
    admin_email: str,
    admin_display_name: str,
    dsn: str | None = None,
) -> dict[str, uuid.UUID]:
    """Idempotent w.r.t. the platform sentinel/catalog checks; NOT idempotent
    for the tenant/admin creation itself -- running it twice with the same
    `entra_tenant_id` will violate the unique constraint on
    tenants.entra_tenant_id, which is the correct behavior (this is a
    one-time onboarding action per tenant, not a repeatable sync)."""
    conn = psycopg2.connect(dsn or settings.migrations_database_url)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            _ensure_platform_tenant(cur)
            _require_role_catalog_seeded(cur)

            tenant_id = uuid.uuid4()
            cur.execute(
                "INSERT INTO tenants (id, name, entra_tenant_id, status) "
                "VALUES (%s, %s, %s, 'active')",
                (str(tenant_id), tenant_name, entra_tenant_id),
            )

            admin_user_id = uuid.uuid4()
            cur.execute(
                "INSERT INTO users "
                "(id, tenant_id, external_idp_subject, email, display_name) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    str(admin_user_id),
                    str(tenant_id),
                    admin_external_idp_subject,
                    admin_email,
                    admin_display_name,
                ),
            )

            cur.execute("SELECT id FROM roles WHERE code = 'tenant_admin'")
            (tenant_admin_role_id,) = cur.fetchone()
            cur.execute(
                "INSERT INTO user_roles (id, tenant_id, user_id, role_id) "
                "VALUES (%s, %s, %s, %s)",
                (str(uuid.uuid4()), str(tenant_id), str(admin_user_id), str(tenant_admin_role_id)),
            )

            # tenant.created is attributed to the reserved sentinel platform
            # tenant -- there is no human platform operator (ADR-001 §4/§9).
            cur.execute(
                "INSERT INTO audit_events "
                "(id, tenant_id, event_type, actor, target_type, target_id, "
                " reason, correlation_id) "
                "VALUES (%s, %s, 'tenant.created', %s, 'tenant', %s, %s, %s)",
                (
                    str(uuid.uuid4()),
                    str(PLATFORM_TENANT_ID),
                    SYSTEM_ACTOR,
                    str(tenant_id),
                    BOOTSTRAP_REASON,
                    str(uuid.uuid4()),
                ),
            )
            cur.execute(
                "INSERT INTO audit_events "
                "(id, tenant_id, event_type, actor, target_type, target_id, "
                " reason, correlation_id) "
                "VALUES (%s, %s, 'user.provisioned', %s, 'user', %s, %s, %s)",
                (
                    str(uuid.uuid4()),
                    str(tenant_id),
                    SYSTEM_ACTOR,
                    str(admin_user_id),
                    BOOTSTRAP_REASON,
                    str(uuid.uuid4()),
                ),
            )
            cur.execute(
                "INSERT INTO audit_events "
                "(id, tenant_id, event_type, actor, target_type, target_id, "
                " reason, correlation_id, policy_version) "
                "VALUES (%s, %s, 'role.assigned', %s, 'user', %s, %s, %s, %s)",
                (
                    str(uuid.uuid4()),
                    str(tenant_id),
                    SYSTEM_ACTOR,
                    str(admin_user_id),
                    BOOTSTRAP_REASON,
                    str(uuid.uuid4()),
                    PERMISSION_POLICY_VERSION,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {"tenant_id": tenant_id, "admin_user_id": admin_user_id}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--entra-tenant-id", required=True)
    parser.add_argument("--admin-external-idp-subject", required=True)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-display-name", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    result = bootstrap_tenant(
        tenant_name=args.tenant_name,
        entra_tenant_id=args.entra_tenant_id,
        admin_external_idp_subject=args.admin_external_idp_subject,
        admin_email=args.admin_email,
        admin_display_name=args.admin_display_name,
    )
    print(f"tenant_id={result['tenant_id']} admin_user_id={result['admin_user_id']}")


if __name__ == "__main__":
    main()
