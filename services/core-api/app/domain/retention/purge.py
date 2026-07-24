"""Time-based retention purge (US-07, ADR-005).

For ONE tenant (the caller sets `SET LOCAL app.current_tenant_id` first, and
runs as the NOBYPASSRLS `vms_purge` role), scrub/delete data older than that
tenant's retention and write one PII-free audit event. RLS+FORCE is the
STRUCTURAL tenant guarantee: every statement below is scoped to the GUC's
tenant by Postgres even though none carries an explicit tenant predicate --
so a forgotten predicate cannot leak across tenants (SP-B2). That is the
whole reason the purge runs as an RLS-subject role, not BYPASSRLS.

Scrub vs delete (ADR-005, from a verified column inventory):
- `users`, `visits` -> SCRUB PII columns in place (referenced by the
  append-only audit trail / FKs; keep the anonymized skeleton). `purged_at`
  marks a scrubbed row so a re-run is idempotent (DA-S1).
- `outbox_messages`, `portal_contact_verifications` -> DELETE (transient;
  naturally idempotent).

Never `updated_at` as the clock (it moves on the scrub itself); each store's
reference timestamp is chosen explicitly below (DA-B1).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, and_, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit import write_audit_event
from app.domain.retention.policy import RetentionCategory, resolve_retention
from app.models import OutboxMessage, PortalContactVerification, User, Visit

REDACTED = "[redacted]"
PURGE_ACTOR = "vms_purge"
PURGE_REASON = "retention_purge"

# On-site / mustering states whose visitor PII must NOT be scrubbed while the
# person is accounted-for (life-safety; also excluded from erasure, DA-B2).
_ON_SITE_STATUSES = ("CheckedIn", "Safe")
# Non-terminal states that, if abandoned, are purged by created_at max-age
# (incl. orphaned NULL-host visits, SP-B3a).
_ABANDONED_STATUSES = ("Requested", "Registered")


async def _cutoff(session: AsyncSession, tenant_id: uuid.UUID, category: RetentionCategory, now: datetime) -> datetime:
    return now - timedelta(seconds=await resolve_retention(session, tenant_id, category))


def _users_predicate(cutoff: datetime):
    return and_(User.purged_at.is_(None), User.status == "disabled", User.disabled_at < cutoff)


def _visits_predicate(cutoff: datetime):
    # Terminal Denied (by decided_at) OR abandoned non-terminal (by
    # created_at). On-site CheckedIn/Safe are deliberately excluded (DA-B2).
    return and_(
        Visit.purged_at.is_(None),
        or_(
            and_(Visit.status == "Denied", Visit.decided_at < cutoff),
            and_(Visit.status.in_(_ABANDONED_STATUSES), Visit.created_at < cutoff),
        ),
    )


async def purge_tenant(
    session: AsyncSession, tenant_id: uuid.UUID, *, execute: bool
) -> dict[str, int]:
    """Purge one tenant (GUC must already be set to `tenant_id`). Returns
    per-category counts. `execute=False` (dry-run) computes the counts via
    SELECT COUNT(*) and mutates nothing / writes no audit."""
    now = datetime.now(timezone.utc)
    counts: dict[str, int] = {}

    users_cutoff = await _cutoff(session, tenant_id, RetentionCategory.STAFF_USERS, now)
    visits_cutoff = await _cutoff(session, tenant_id, RetentionCategory.VISITS, now)
    outbox_cutoff = await _cutoff(session, tenant_id, RetentionCategory.OUTBOX, now)
    cv_cutoff = await _cutoff(session, tenant_id, RetentionCategory.CONTACT_VERIFICATIONS, now)

    if not execute:
        counts["staff_users"] = (
            await session.execute(select(func.count()).select_from(User).where(_users_predicate(users_cutoff)))
        ).scalar_one()
        counts["visits"] = (
            await session.execute(select(func.count()).select_from(Visit).where(_visits_predicate(visits_cutoff)))
        ).scalar_one()
        counts["outbox_messages"] = (
            await session.execute(select(func.count()).select_from(OutboxMessage).where(OutboxMessage.created_at < outbox_cutoff))
        ).scalar_one()
        counts["contact_verifications"] = (
            await session.execute(select(func.count()).select_from(PortalContactVerification).where(PortalContactVerification.created_at < cv_cutoff))
        ).scalar_one()
        return counts

    # --- users: scrub PII (NOT NULL -> markers; external_idp_subject unique
    # per tenant -> per-row-unique marker), stamp purged_at ---
    counts["staff_users"] = (
        await session.execute(
            update(User)
            .where(_users_predicate(users_cutoff))
            .values(
                email=REDACTED + "@redacted.invalid",
                display_name=REDACTED,
                external_idp_subject=func.concat("purged-", cast(User.id, String)),
                purged_at=now,
            )
        )
    ).rowcount

    # --- visits: scrub the full PII column inventory (incl. purpose), stamp ---
    counts["visits"] = (
        await session.execute(
            update(Visit)
            .where(_visits_predicate(visits_cutoff))
            .values(
                visitor_full_name=REDACTED,
                contact_value=REDACTED,
                host_hint=None,
                purpose=None,
                denial_reason=None,
                checkin_code_hash=None,
                purged_at=now,
            )
        )
    ).rowcount

    # --- outbox: delete by age across ALL statuses (dispatched included) ---
    counts["outbox_messages"] = (
        await session.execute(delete(OutboxMessage).where(OutboxMessage.created_at < outbox_cutoff))
    ).rowcount

    # --- contact_verifications: delete by age ---
    counts["contact_verifications"] = (
        await session.execute(
            delete(PortalContactVerification).where(PortalContactVerification.created_at < cv_cutoff)
        )
    ).rowcount

    # --- one PII-free audit event per tenant (DA-S4 / SP): counts + cutoffs ---
    await write_audit_event(
        session,
        tenant_id=tenant_id,
        event_type="retention.purge",
        actor=PURGE_ACTOR,
        target_type="tenant",
        target_id=tenant_id,
        reason=PURGE_REASON,
        correlation_id=uuid.uuid4(),
        details={
            "counts": counts,
            "cutoffs": {
                "staff_users": users_cutoff.isoformat(),
                "visits": visits_cutoff.isoformat(),
                "outbox_messages": outbox_cutoff.isoformat(),
                "contact_verifications": cv_cutoff.isoformat(),
            },
        },
    )
    await session.flush()
    return counts
