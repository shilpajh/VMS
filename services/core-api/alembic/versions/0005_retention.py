"""retention config + purge/erasure support (US-07, ADR-005)

Adds:
- `retention_policies` -- per-tenant, per-category retention OVERRIDES
  (absence -> the config default). Tenant-scoped, RLS ENABLE+FORCE (ADR-001's
  pattern): the future compliance API reads/writes it under RLS, and the
  purge reads it under the per-tenant GUC (the one legitimate RLS-scoped ops
  read). `data_category` maps to a table: staff_users->users,
  visits->visits, outbox_messages->outbox_messages,
  contact_verifications->portal_contact_verifications.
- `audit_events.details` (nullable JSONB) -- structured metadata for the
  purge (counts/policy/cutoff) and erasure (keyed-HMAC subject_ref/counts).
  Additive; the append-only, purge-exempt no-PII-in-details contract is in
  ADR-005.
- `users.disabled_at` -- the retention reference for staff (there was none;
  DA-B1). Set by the disable path. `users.purged_at` / `visits.purged_at` --
  scrub idempotency markers (DA-S1): a scrubbed row still matches "expired",
  so the scrub predicate carries `purged_at IS NULL`.
- Grants for the `vms_purge` role (roles.sql creates it, NOBYPASSRLS): the
  narrow scrub/delete privileges only -- UPDATE on the scrub tables (never
  DELETE, which would break the audit linkage), DELETE on the transient
  tables, SELECT on what it reads, INSERT on the audit sink.

Revision ID: 0005_retention
Revises: 0004_portal_contact_verification
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_retention"
down_revision = "0004_portal_contact_verification"
branch_labels = None
depends_on = None

RLS_TABLE = "retention_policies"


def upgrade() -> None:
    # --- retention_policies ---
    op.create_table(
        RLS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("data_category", sa.String(32), nullable=False),
        sa.Column("retention_seconds", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "data_category IN ('staff_users', 'visits', 'outbox_messages', 'contact_verifications')",
            name="ck_retention_policies_category",
        ),
        sa.CheckConstraint("retention_seconds > 0", name="ck_retention_policies_positive"),
        sa.UniqueConstraint("tenant_id", "data_category", name="uq_retention_policies_tenant_category"),
    )
    op.create_index("ix_retention_policies_tenant_id", RLS_TABLE, ["tenant_id"])
    op.execute(f'ALTER TABLE "{RLS_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{RLS_TABLE}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{RLS_TABLE}" '
        f"USING (tenant_id = current_setting('app.current_tenant_id')::uuid) "
        f"WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )

    # --- audit_events.details (additive, nullable) ---
    op.add_column("audit_events", sa.Column("details", postgresql.JSONB, nullable=True))

    # --- retention reference + idempotency markers ---
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("visits", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True))

    # --- vms_purge grants: narrow, scrub=UPDATE (never DELETE on referenced
    # tables), delete on transient, read what it needs, INSERT audit only ---
    op.execute("GRANT SELECT ON tenants TO vms_purge")
    op.execute("GRANT SELECT ON retention_policies TO vms_purge")
    op.execute("GRANT SELECT, UPDATE ON users TO vms_purge")
    op.execute("GRANT SELECT, UPDATE ON visits TO vms_purge")
    op.execute("GRANT SELECT, DELETE ON outbox_messages TO vms_purge")
    op.execute("GRANT SELECT, DELETE ON portal_contact_verifications TO vms_purge")
    op.execute("GRANT SELECT, INSERT ON audit_events TO vms_purge")


def downgrade() -> None:
    op.execute("REVOKE ALL ON audit_events FROM vms_purge")
    op.execute("REVOKE ALL ON portal_contact_verifications FROM vms_purge")
    op.execute("REVOKE ALL ON outbox_messages FROM vms_purge")
    op.execute("REVOKE ALL ON visits FROM vms_purge")
    op.execute("REVOKE ALL ON users FROM vms_purge")
    op.execute("REVOKE ALL ON retention_policies FROM vms_purge")
    op.execute("REVOKE ALL ON tenants FROM vms_purge")

    op.drop_column("visits", "purged_at")
    op.drop_column("users", "purged_at")
    op.drop_column("users", "disabled_at")
    op.drop_column("audit_events", "details")

    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{RLS_TABLE}"')
    op.execute(f'ALTER TABLE "{RLS_TABLE}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{RLS_TABLE}" DISABLE ROW LEVEL SECURITY')
    op.drop_table(RLS_TABLE)
