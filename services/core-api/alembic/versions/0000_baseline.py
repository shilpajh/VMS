"""baseline (empty)

Revision ID: 0000_baseline
Revises:
Create Date: 2026-07-23

Empty on purpose: confirms the Alembic pipeline runs end to end before any
domain table exists. The first real schema (tenants/users/roles) is US-10's,
produced through /plan-story per AGENTS.md.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0000_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
