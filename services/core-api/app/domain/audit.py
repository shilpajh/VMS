"""Append-only audit event writer (US-10, ADR-001 §2/§9, B2).

Every identity action writes exactly one `audit_events` row carrying the
same 5-field shape the visit state machine requires: actor, timestamp
(`created_at`, server-generated), policy_version (role changes only),
reason, correlation_id -- plus target_type/target_id identifying the
affected resource. Never UPDATEd/DELETEd (enforced by the DB grants from
the 0001 migration, not just by convention here).

Never pass PII (email/display_name) as `actor`/`reason`/etc. -- use stable
identifiers (user id, external_idp_subject/oid, or the fixed "system"
marker) only.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent

# Fixed reserved actor for platform-level actions with no human operator
# (ADR-001 §4/§9) -- currently only `tenant.created`, emitted by the ops
# bootstrap script (task 11).
SYSTEM_ACTOR = "system"


async def write_audit_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_type: str,
    actor: str,
    target_type: str,
    target_id: uuid.UUID,
    reason: str,
    correlation_id: uuid.UUID,
    policy_version: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        correlation_id=correlation_id,
        policy_version=policy_version,
    )
    session.add(event)
    await session.flush()
    return event
