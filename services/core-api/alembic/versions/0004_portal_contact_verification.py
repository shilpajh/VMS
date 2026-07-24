"""portal contact verification (OTP) + portal submission fields (US-13a)

Adds:
- `portal_contact_verifications` -- the ephemeral OTP/verification-token
  store (ADR-004). Tenant-scoped, RLS ENABLE+FORCE (ADR-001's pattern,
  reused verbatim), even though a row exists before any visit does: tenant
  context is set from `tenant_slug` via `resolve_public_tenant` before any
  row is written. Two indexes: `(tenant_id, contact_channel, contact_value)`
  for the verify/supersede path, and `verification_token_hash` for the
  submission-consume path.
- Five nullable `visits` columns (PRD 3.1 + US-13a): `purpose`,
  `group_type` (CHECK individual/group), `expected_group_size`,
  `identity_verification_choice` (CHECK upload_now/send_to_host),
  `contact_verified` (bool -- non-PII trust property, true when the visit
  was created via a validated verification token). All nullable, no
  backfill: existing/historical visits predate these fields.

`vms_app` gets SELECT/INSERT/UPDATE/DELETE on
`portal_contact_verifications` -- unlike every other tenant table, the
request path legitimately DELETEs here (single-use token consumption is a
delete; abandoned/expired rows are purged by the ops role via the standing
retention job US-07 owns, ADR-004). No DELETE on `visits` (unchanged).

Revision ID: 0004_portal_contact_verification
Revises: 0003_visit_checkin
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_portal_contact_verification"
down_revision = "0003_visit_checkin"
branch_labels = None
depends_on = None

RLS_TABLE = "portal_contact_verifications"


def upgrade() -> None:
    # --- portal_contact_verifications ---
    op.create_table(
        RLS_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("contact_channel", sa.String(16), nullable=False),
        sa.Column("contact_value", sa.String(320), nullable=False),
        sa.Column("otp_hash", sa.String(128), nullable=False),
        sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("otp_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("superseded", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("privacy_notice_acknowledged", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("privacy_notice_version", sa.String(32), nullable=False),
        sa.Column("verification_token_hash", sa.String(128), nullable=True),
        sa.Column("verification_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "contact_channel IN ('email', 'sms')", name="ck_pcv_contact_channel"
        ),
    )
    op.create_index(
        "ix_pcv_tenant_channel_value",
        RLS_TABLE,
        ["tenant_id", "contact_channel", "contact_value"],
    )
    op.create_index("ix_pcv_verification_token_hash", RLS_TABLE, ["verification_token_hash"])

    # RLS: fail-closed, USING + WITH CHECK (ADR-001 §1, reused verbatim).
    op.execute(f'ALTER TABLE "{RLS_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{RLS_TABLE}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{RLS_TABLE}" '
        f"USING (tenant_id = current_setting('app.current_tenant_id')::uuid) "
        f"WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )
    # Request path DELETEs here (token consume); purge is the ops role's job.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {RLS_TABLE} TO vms_app")

    # --- new visits columns (all nullable, no backfill) ---
    op.add_column("visits", sa.Column("purpose", sa.String(255), nullable=True))
    op.add_column("visits", sa.Column("group_type", sa.String(16), nullable=True))
    op.add_column("visits", sa.Column("expected_group_size", sa.Integer, nullable=True))
    op.add_column(
        "visits", sa.Column("identity_verification_choice", sa.String(16), nullable=True)
    )
    op.add_column(
        "visits",
        sa.Column("contact_verified", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_check_constraint(
        "ck_visits_group_type", "visits", "group_type IS NULL OR group_type IN ('individual', 'group')"
    )
    op.create_check_constraint(
        "ck_visits_identity_verification_choice",
        "visits",
        "identity_verification_choice IS NULL OR "
        "identity_verification_choice IN ('upload_now', 'send_to_host')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_visits_identity_verification_choice", "visits", type_="check")
    op.drop_constraint("ck_visits_group_type", "visits", type_="check")
    op.drop_column("visits", "contact_verified")
    op.drop_column("visits", "identity_verification_choice")
    op.drop_column("visits", "expected_group_size")
    op.drop_column("visits", "group_type")
    op.drop_column("visits", "purpose")

    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{RLS_TABLE}"')
    op.execute(f'ALTER TABLE "{RLS_TABLE}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{RLS_TABLE}" DISABLE ROW LEVEL SECURITY')
    op.drop_table(RLS_TABLE)
