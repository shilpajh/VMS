"""tenancy and identity schema (US-10)

Introduces the Tenant & Identity domain per ADR-001:
tenants, users, roles, permissions, role_permissions, user_roles, and the
first cut of the append-only audit_events table.

Includes:
- RLS (ENABLE + FORCE, USING + WITH CHECK, fail-closed single-argument
  current_setting) on every tenant-scoped table.
- Grants scoping the non-superuser `vms_app` role to exactly what the
  request path needs (read-only on global catalogs; no grants at all on
  `tenants` writes or on UPDATE/DELETE of `audit_events`, enforcing
  "no cross-tenant runtime endpoint" and "audit is append-only" at the DB
  layer, not just in application code).
- The seed sentinel `platform` tenant row and the role_permissions catalog
  (ADR-001 §3), tagged with permission policy version "v1".

Revision ID: 0001_tenancy_identity
Revises: 0000_baseline
Create Date: 2026-07-23
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_tenancy_identity"
down_revision = "0000_baseline"
branch_labels = None
depends_on = None

PERMISSION_POLICY_VERSION = "v1"

PLATFORM_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
PLATFORM_TENANT_ENTRA_TENANT_ID = "platform-sentinel-no-entra-tenant"

ROLE_TENANT_ADMIN_ID = uuid.UUID("27530b2d-9fd8-4de5-b74b-6d6112846f5f")
ROLE_HOST_ID = uuid.UUID("6695ce51-ac97-4137-8dd9-259c804e3056")
ROLE_RECEPTION_SECURITY_ID = uuid.UUID("f653bf6f-03af-411e-8b07-26bb51cbd668")
ROLE_DASHBOARD_VIEWER_ID = uuid.UUID("7750c75f-4e38-4257-b31c-7403a6982afb")

PERM_MANAGE_USERS_ID = uuid.UUID("350de4b0-6a24-47b5-89e4-ca27297406e7")
PERM_MANAGE_ROLES_ID = uuid.UUID("e4b01a24-ab3a-435b-95b5-0a464a0caa2c")
PERM_VIEW_DASHBOARDS_ID = uuid.UUID("7209f2a6-87b4-4350-bc0e-837256970765")
PERM_APPROVE_DENY_VISITS_ID = uuid.UUID("55ffe1e4-6c47-42c4-a25f-cec31f1179ee")
PERM_APPROVE_DENY_HOLDS_ID = uuid.UUID("66017d55-35ba-4bfa-a162-5c3f53cd0eff")
PERM_CHECKIN_CONFIRM_ID = uuid.UUID("65377951-b418-4008-80a0-4cbcdb34d536")

# role_code -> [(permission_id, permission_code, description)]
ROLES = [
    (ROLE_TENANT_ADMIN_ID, "tenant_admin", "Tenant Administrator"),
    (ROLE_HOST_ID, "host", "Host"),
    (ROLE_RECEPTION_SECURITY_ID, "reception_security", "Reception / Security"),
    (ROLE_DASHBOARD_VIEWER_ID, "dashboard_viewer", "Dashboard Viewer"),
]

PERMISSIONS = [
    (PERM_MANAGE_USERS_ID, "manage_users", "Create/enable/disable users within a tenant"),
    (PERM_MANAGE_ROLES_ID, "manage_roles", "Assign/revoke roles within a tenant"),
    (PERM_VIEW_DASHBOARDS_ID, "view_dashboards", "View operational dashboards"),
    (
        PERM_APPROVE_DENY_VISITS_ID,
        "approve_deny_visits",
        "Approve/deny Requested visits (host transitions)",
    ),
    (
        PERM_APPROVE_DENY_HOLDS_ID,
        "approve_deny_holds",
        "Release/reject a Held visit (visit-lifecycle.yaml required_permission)",
    ),
    (PERM_CHECKIN_CONFIRM_ID, "checkin_confirm", "Confirm check-in at reception/kiosk"),
]

# ADR-001 §3 first-cut seed.
ROLE_PERMISSIONS = [
    (ROLE_TENANT_ADMIN_ID, PERM_MANAGE_USERS_ID),
    (ROLE_TENANT_ADMIN_ID, PERM_MANAGE_ROLES_ID),
    (ROLE_TENANT_ADMIN_ID, PERM_VIEW_DASHBOARDS_ID),
    (ROLE_HOST_ID, PERM_APPROVE_DENY_VISITS_ID),
    (ROLE_RECEPTION_SECURITY_ID, PERM_APPROVE_DENY_HOLDS_ID),
    (ROLE_RECEPTION_SECURITY_ID, PERM_CHECKIN_CONFIRM_ID),
    (ROLE_DASHBOARD_VIEWER_ID, PERM_VIEW_DASHBOARDS_ID),
]

# Tenant-scoped tables subject to RLS (ADR-001 §1). `tenants`, `roles`,
# `permissions`, `role_permissions` are explicitly tenant-global reference
# tables and are NOT RLS-scoped -- see model docstrings / ADR-001 §2.
RLS_TABLES = ["users", "user_roles", "audit_events"]


def _enable_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    # Fail-closed, single-argument current_setting: raises if the GUC is
    # unset rather than silently treating an unscoped session as "see all"
    # (the two-argument `current_setting(..., true)` missing-ok form is
    # deliberately NOT used -- ADR-001 §1).
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" '
        f"USING (tenant_id = current_setting('app.current_tenant_id')::uuid) "
        f"WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )


def _disable_rls(table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("entra_tenant_id", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_tenants_status"),
    )

    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("external_idp_subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "tenant_id", "external_idp_subject", name="uq_users_tenant_external_idp_subject"
        ),
        # Prerequisite for user_roles' composite FK -- Postgres will not
        # create a composite FK without a matching unique constraint here
        # (ADR-001 §2, Risks).
        sa.UniqueConstraint("id", "tenant_id", name="uq_users_id_tenant_id"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("roles.id"), primary_key=True
        ),
        sa.Column(
            "permission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("permissions.id"),
            primary_key=True,
        ),
        sa.Column("policy_version", sa.String(32), nullable=False),
    )

    op.create_table(
        "user_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("roles.id"), nullable=False
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "role_id", name="uq_user_roles_tenant_user_role"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_user_roles_user_tenant",
        ),
    )
    op.create_index("ix_user_roles_tenant_id", "user_roles", ["tenant_id"])
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])

    # --- RLS: fail-closed, USING + WITH CHECK, on every tenant-scoped table ---
    for table in RLS_TABLES:
        _enable_rls(table)

    # --- Grants: scope vms_app to exactly what the request path needs ---
    # Tenant-global catalogs: read-only. There is deliberately no grant that
    # would let the app write `tenants` -- tenant creation is ops-script
    # only (ADR-001 §4), enforced here at the DB layer too, not just by the
    # absence of an API route.
    op.execute("GRANT SELECT ON tenants TO vms_app")
    op.execute("GRANT SELECT ON roles TO vms_app")
    op.execute("GRANT SELECT ON permissions TO vms_app")
    op.execute("GRANT SELECT ON role_permissions TO vms_app")
    # Users: read, JIT-provision (INSERT), enable/disable (UPDATE). No
    # DELETE -- users are disabled, never deleted, from the API.
    op.execute("GRANT SELECT, INSERT, UPDATE ON users TO vms_app")
    # user_roles: full CRUD -- assign (INSERT), list (SELECT), revoke
    # (DELETE). No UPDATE (assignments are add/remove, not edited in place).
    op.execute("GRANT SELECT, INSERT, DELETE ON user_roles TO vms_app")
    # audit_events: append-only. SELECT for internal queries, INSERT to
    # write events. No UPDATE, no DELETE, ever -- there is deliberately no
    # grant statement for either, so an attempt is rejected at the DB layer
    # even if application code had a bug.
    op.execute("GRANT SELECT, INSERT ON audit_events TO vms_app")

    # --- Seed data (ADR-001 §3, §4) ---
    now_params = {"policy_version": PERMISSION_POLICY_VERSION}

    op.execute(
        sa.text(
            "INSERT INTO tenants (id, name, entra_tenant_id, status) "
            "VALUES (:id, :name, :entra_tenant_id, 'active') "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=PLATFORM_TENANT_ID,
            name="Platform (reserved sentinel)",
            entra_tenant_id=PLATFORM_TENANT_ENTRA_TENANT_ID,
        )
    )

    for role_id, code, name in ROLES:
        op.execute(
            sa.text(
                "INSERT INTO roles (id, code, name, is_system) "
                "VALUES (:id, :code, :name, true) ON CONFLICT (id) DO NOTHING"
            ).bindparams(id=role_id, code=code, name=name)
        )

    for perm_id, code, description in PERMISSIONS:
        op.execute(
            sa.text(
                "INSERT INTO permissions (id, code, description) "
                "VALUES (:id, :code, :description) ON CONFLICT (id) DO NOTHING"
            ).bindparams(id=perm_id, code=code, description=description)
        )

    for role_id, perm_id in ROLE_PERMISSIONS:
        op.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id, policy_version) "
                "VALUES (:role_id, :permission_id, :policy_version) "
                "ON CONFLICT (role_id, permission_id) DO NOTHING"
            ).bindparams(role_id=role_id, permission_id=perm_id, **now_params)
        )


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        _disable_rls(table)

    op.drop_table("audit_events")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("users")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("tenants")
