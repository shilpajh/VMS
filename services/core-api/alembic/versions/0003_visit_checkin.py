"""visits check-in columns (US-01)

Adds three nullable columns to `visits`, wiring the `Registered ->
CheckedIn` (`checkin_verified`) transition's data needs:

- `checkin_code_expires_at` -- persists the value US-11's `approve_visit`
  already computed transiently (only ever copied onto
  `outbox_messages.not_valid_after` before this migration) so the domain
  layer can enforce the `within_visit_window` guard by reading the `visits`
  row alone, never `outbox_messages` (a dispatch artifact, not the domain's
  source of truth). A known-interim substitution -- see US-01 plan, Part A
  Risks -- for a real scheduled-arrival-window field no story has built yet.
- `checked_in_by_user_id` / `checked_in_at` -- decision metadata for the
  check-in action itself, mirroring `decided_by_user_id`/`decided_at`'s
  existing pattern for the Requested->{Registered,Denied} decision.
  `checked_in_by_user_id` gets the same nullable composite FK
  `(checked_in_by_user_id, tenant_id) -> users(id, tenant_id)` as
  `host_user_id` (ADR-001 §2's pattern, reused verbatim).

No RBAC seed, no policy-version bump -- US-01 plan's Scope amendment: the
`checkin_confirm` permission ("Confirm check-in at reception/kiosk")
already exists, seeded by 0001_tenancy_identity for `reception_security`,
anticipating exactly this story.

Revision ID: 0003_visit_checkin
Revises: 0002_visits_and_outbox
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003_visit_checkin"
down_revision = "0002_visits_and_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "visits", sa.Column("checkin_code_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "visits", sa.Column("checked_in_by_user_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "visits", sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_visits_checked_in_by_user_tenant",
        "visits",
        "users",
        ["checked_in_by_user_id", "tenant_id"],
        ["id", "tenant_id"],
    )
    op.create_index("ix_visits_checked_in_by_user_id", "visits", ["checked_in_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_visits_checked_in_by_user_id", table_name="visits")
    op.drop_constraint("fk_visits_checked_in_by_user_tenant", "visits", type_="foreignkey")
    op.drop_column("visits", "checked_in_at")
    op.drop_column("visits", "checked_in_by_user_id")
    op.drop_column("visits", "checkin_code_expires_at")
