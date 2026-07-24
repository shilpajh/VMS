"""Retention policy resolution (US-07, ADR-005).

`resolve_retention(session, tenant_id, category)` returns the tenant's
`retention_policies` override for that category, or the placeholder config
default when no override exists. The placeholder windows are the prior
stories' deferred values -- NOT final legal policy; the real values are a
human compliance owner's decision (the open DPDP GA gate, Constraint 1).

The override read is RLS-scoped: the purge sets the per-tenant GUC before
calling this, so it only ever sees the current tenant's policy row.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RetentionPolicy


class RetentionCategory(str, enum.Enum):
    # value == the retention_policies.data_category string (ADR-005 mapping).
    STAFF_USERS = "staff_users"          # -> users
    VISITS = "visits"                    # -> visits
    OUTBOX = "outbox_messages"           # -> outbox_messages
    CONTACT_VERIFICATIONS = "contact_verifications"  # -> portal_contact_verifications


# PLACEHOLDER defaults (seconds) -- NOT final DPDP policy (Constraint 1).
# Sourced from the prior stories' deferred windows: users 180d post-disable,
# visits 90d, outbox 7d, contact-verifications 1d.
DEFAULT_RETENTION_SECONDS: dict[RetentionCategory, int] = {
    RetentionCategory.STAFF_USERS: 180 * 24 * 3600,
    RetentionCategory.VISITS: 90 * 24 * 3600,
    RetentionCategory.OUTBOX: 7 * 24 * 3600,
    RetentionCategory.CONTACT_VERIFICATIONS: 1 * 24 * 3600,
}


async def resolve_retention(
    session: AsyncSession, tenant_id: uuid.UUID, category: RetentionCategory
) -> int:
    override = (
        await session.execute(
            select(RetentionPolicy.retention_seconds).where(
                RetentionPolicy.tenant_id == tenant_id,
                RetentionPolicy.data_category == category.value,
            )
        )
    ).scalar_one_or_none()
    return override if override is not None else DEFAULT_RETENTION_SECONDS[category]
