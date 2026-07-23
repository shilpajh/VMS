"""visits and outbox_messages schema (US-11)

Introduces the Visitor & Visits domain's first two tables per ADR-001
(tenancy/RLS pattern, reused verbatim) and ADR-002 (transactional outbox):

- `tenants.public_slug` -- amend, the public portal's tenant handle (task 1).
- `permissions`/`role_permissions` seed addition: `view_visits`, granted to
  `reception_security` and `tenant_admin`, bumping the permission policy
  version "v1" -> "v2" (task 1).
- `visits` -- the visit lifecycle record (task 2).
- `outbox_messages` -- the generic transactional-outbox table, first used
  for `visit.checkin_code.dispatch` (task 2, ADR-002 §1).

Both new tables: RLS ENABLE + FORCE, USING + WITH CHECK, fail-closed
single-argument current_setting (ADR-001 §1, reused verbatim). Grants:
`vms_app` gets SELECT, INSERT, UPDATE on both -- no DELETE (purge is an
ops-role job, ADR-001 §4 precedent / ADR-002 §1).

Revision ID: 0002_visits_and_outbox
Revises: 0001_tenancy_identity
Create Date: 2026-07-23
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_visits_and_outbox"
down_revision = "0001_tenancy_identity"
branch_labels = None
depends_on = None

PERMISSION_POLICY_VERSION = "v2"

PERM_VIEW_VISITS_ID = uuid.UUID("8a2f6c1d-2b8a-4f2e-9e0e-2f6b6f7a1c10")

# Existing role ids from 0001_tenancy_identity -- reused as-is, this is an
# additive seed change, not a redesign of US-10's RBAC model.
ROLE_TENANT_ADMIN_ID = uuid.UUID("27530b2d-9fd8-4de5-b74b-6d6112846f5f")
ROLE_RECEPTION_SECURITY_ID = uuid.UUID("f653bf6f-03af-411e-8b07-26bb51cbd668")

# New RLS-scoped tables added by this migration.
RLS_TABLES = ["visits", "outbox_messages"]


def _enable_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
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
    # --- Task 1: tenants.public_slug ---
    op.add_column("tenants", sa.Column("public_slug", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_tenants_public_slug", "tenants", ["public_slug"])

    # --- Task 1: view_visits permission + role_permissions seed ---
    op.execute(
        sa.text(
            "INSERT INTO permissions (id, code, description) "
            "VALUES (:id, :code, :description) ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=PERM_VIEW_VISITS_ID,
            code="view_visits",
            description="View all visits within a tenant",
        )
    )
    for role_id in (ROLE_RECEPTION_SECURITY_ID, ROLE_TENANT_ADMIN_ID):
        op.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id, policy_version) "
                "VALUES (:role_id, :permission_id, :policy_version) "
                "ON CONFLICT (role_id, permission_id) DO NOTHING"
            ).bindparams(
                role_id=role_id,
                permission_id=PERM_VIEW_VISITS_ID,
                policy_version=PERMISSION_POLICY_VERSION,
            )
        )

    # --- Task 2: visits ---
    op.create_table(
        "visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="Requested"),
        sa.Column("visitor_full_name", sa.String(255), nullable=False),
        sa.Column("contact_channel", sa.String(16), nullable=False),
        sa.Column("contact_value", sa.String(320), nullable=False),
        sa.Column("host_hint", sa.String(255), nullable=True),
        sa.Column("host_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tracking_reference", sa.String(32), nullable=False, unique=True),
        sa.Column("checkin_code_hash", sa.String(64), nullable=True),
        sa.Column("denial_reason", sa.Text, nullable=True),
        sa.Column(
            "privacy_notice_acknowledged", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column("privacy_notice_version", sa.String(32), nullable=False),
        sa.Column("submission_dedup_key", sa.String(64), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('Requested', 'Registered', 'AwaitingApproval', "
            "'AwaitingDualSignoff', 'Held', 'CheckedIn', 'CheckedOut', "
            "'Denied', 'Safe')",
            name="ck_visits_status",
        ),
        sa.CheckConstraint(
            "contact_channel IN ('email', 'sms')", name="ck_visits_contact_channel"
        ),
        sa.ForeignKeyConstraint(
            ["host_user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_visits_host_user_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id", "submission_dedup_key", name="uq_visits_tenant_dedup_key"
        ),
    )
    op.create_index("ix_visits_tenant_id", "visits", ["tenant_id"])
    op.create_index("ix_visits_host_user_id", "visits", ["host_user_id"])

    # --- Task 2: outbox_messages (ADR-002 §1) ---
    op.create_table(
        "outbox_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("message_type", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("payload", sa.LargeBinary, nullable=False),
        sa.Column("payload_key_ref", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("not_valid_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'dispatched', 'failed')", name="ck_outbox_messages_status"
        ),
    )
    op.create_index("ix_outbox_messages_tenant_id", "outbox_messages", ["tenant_id"])

    # --- RLS: fail-closed, USING + WITH CHECK (ADR-001 §1, reused verbatim) ---
    for table in RLS_TABLES:
        _enable_rls(table)

    # --- Grants ---
    # visits: request path reads, creates (portal submission), updates
    # (host approve/deny transitions). No DELETE -- visits are never deleted
    # from the API; retention/purge (US-11 review Should-fix #3) is a future
    # US-07 ops-role job.
    op.execute("GRANT SELECT, INSERT, UPDATE ON visits TO vms_app")
    # outbox_messages: request path INSERTs the dispatch-intent row inside
    # the approval transaction; SELECT/UPDATE reserved for a future relay
    # worker role (ADR-002 §6 -- NOT vms_app; the worker is not built in
    # this story). No DELETE -- purge is the ops/vms_migrator role
    # (ADR-002 §5).
    op.execute("GRANT SELECT, INSERT, UPDATE ON outbox_messages TO vms_app")


def downgrade() -> None:
    for table in reversed(RLS_TABLES):
        _disable_rls(table)

    op.drop_table("outbox_messages")
    op.drop_table("visits")

    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id = :permission_id"
        ).bindparams(permission_id=PERM_VIEW_VISITS_ID)
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE id = :id").bindparams(id=PERM_VIEW_VISITS_ID)
    )

    op.drop_constraint("uq_tenants_public_slug", "tenants", type_="unique")
    op.drop_column("tenants", "public_slug")
