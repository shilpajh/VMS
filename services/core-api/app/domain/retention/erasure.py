"""Right-to-erasure (US-07, ADR-005). On-demand deletion of ONE data
subject's PII within ONE tenant, completing in seconds (the ≤72h SLA). Runs
as the NOBYPASSRLS `vms_purge` role with the tenant GUC set, so RLS+FORCE
structurally scopes every statement (SP-B2).

Completeness (DA-B3): a visitor's `contact_value` is on `visits` AND
`portal_contact_verifications`, and their `outbox_messages` anchor to BOTH
visit ids and verification ids (`portal.otp.dispatch` uses
`aggregate_type='portal_contact_verification'`, ADR-004 §4). All are erased.

Life-safety carve-out (DA-B2): erasure REFUSES a subject with an on-site
(`CheckedIn`) or mustering (`Safe`) visit -- you cannot anonymize someone
you must still account for in an evacuation. The operator completes checkout
first. (Compliance-owner-confirmable exception.)

Audit (SP-B1): the erasure audit's `subject_ref` is a KEYED HMAC of the
identifier -- never a bare digest (reversible for low-entropy contacts) and
never the raw contact -- because `audit_events` is append-only and
purge-exempt, so anything there is permanently un-erasable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, and_, cast, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto.hmac_hash import HmacKeyProvider, hmac_hash
from app.domain.audit import write_audit_event
from app.domain.retention.purge import REDACTED, _ON_SITE_STATUSES
from app.models import OutboxMessage, PortalContactVerification, User, Visit

ERASE_ACTOR = "vms_purge"
ERASE_REASON = "retention_erasure"

# Per-row-unique redacted marker for the NOT-NULL, unique-per-tenant
# users.external_idp_subject (matches the purge's scrub).
_SCRUBBED_SUBJECT = func.concat("purged-", cast(User.id, String))


class OnSiteErasureRefused(Exception):
    """Raised when the subject has a CheckedIn/Safe visit -- erasure would
    break evacuation accounting (DA-B2). Complete checkout first."""


async def _audit_erasure(
    session: AsyncSession, tenant_id: uuid.UUID, subject_ref: str, counts: dict[str, int]
) -> None:
    await write_audit_event(
        session,
        tenant_id=tenant_id,
        event_type="retention.erasure",
        actor=ERASE_ACTOR,
        target_type="tenant",
        target_id=tenant_id,
        reason=ERASE_REASON,
        correlation_id=uuid.uuid4(),
        # subject_ref is a keyed HMAC -- non-reversible, no raw contact.
        details={"subject_ref": subject_ref, "counts": counts},
    )


async def erase_visitor(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    contact_channel: str,
    contact_value: str,
    hmac_provider: HmacKeyProvider,
    execute: bool,
) -> dict[str, int]:
    """Erase a visitor subject (by contact) across visits + contact-
    verifications + outbox (both anchors). GUC must be set to `tenant_id`."""
    visit_pred = and_(Visit.contact_channel == contact_channel, Visit.contact_value == contact_value)
    cv_pred = and_(
        PortalContactVerification.contact_channel == contact_channel,
        PortalContactVerification.contact_value == contact_value,
    )

    onsite = (
        await session.execute(
            select(func.count()).select_from(Visit).where(visit_pred, Visit.status.in_(_ON_SITE_STATUSES))
        )
    ).scalar_one()
    if onsite > 0:
        raise OnSiteErasureRefused(
            "subject has an on-site (CheckedIn/Safe) visit; complete checkout before erasure"
        )

    # Collect anchor id sets BEFORE scrubbing (the scrub blanks contact_value).
    visit_ids = [r[0] for r in (await session.execute(select(Visit.id).where(visit_pred))).all()]
    verification_ids = [
        r[0] for r in (await session.execute(select(PortalContactVerification.id).where(cv_pred))).all()
    ]

    anchors = visit_ids + verification_ids
    outbox_pred = OutboxMessage.aggregate_id.in_(anchors)
    outbox_count = (
        (await session.execute(select(func.count()).select_from(OutboxMessage).where(outbox_pred))).scalar_one()
        if anchors
        else 0
    )
    counts = {
        "visits": len(visit_ids),
        "contact_verifications": len(verification_ids),
        "outbox_messages": outbox_count,
    }

    if execute:
        if anchors:
            await session.execute(delete(OutboxMessage).where(outbox_pred))
        await session.execute(delete(PortalContactVerification).where(cv_pred))
        await session.execute(
            update(Visit)
            .where(visit_pred)
            .values(
                visitor_full_name=REDACTED, contact_value=REDACTED, host_hint=None,
                purpose=None, denial_reason=None, checkin_code_hash=None,
                purged_at=datetime.now(timezone.utc),
            )
        )
        await _audit_erasure(
            session, tenant_id, hmac_hash(f"{contact_channel}:{contact_value}", hmac_provider), counts
        )
        await session.flush()
    return counts


async def erase_staff(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    email: str,
    hmac_provider: HmacKeyProvider,
    execute: bool,
) -> dict[str, int]:
    """Erase a staff subject (by email) -- scrub the `users` row. GUC must be
    set to `tenant_id`."""
    pred = and_(User.email == email, User.purged_at.is_(None))
    n = (await session.execute(select(func.count()).select_from(User).where(pred))).scalar_one()
    counts = {"staff_users": n}
    if execute and n:
        await session.execute(
            update(User)
            .where(pred)
            .values(
                email=REDACTED + "@redacted.invalid",
                display_name=REDACTED,
                external_idp_subject=_SCRUBBED_SUBJECT,
                purged_at=datetime.now(timezone.utc),
            )
        )
        await _audit_erasure(session, tenant_id, hmac_hash(f"staff:{email}", hmac_provider), counts)
        await session.flush()
    return counts
