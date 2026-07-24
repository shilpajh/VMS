"""Visit approval/denial orchestration (US-11, task 10).

Each of `approve_visit`/`deny_visit` is one transaction: a guarded
conditional UPDATE (`WHERE status = 'Requested'`, race-safe -- the DB-layer
half of "enforce transitions in the domain layer + a DB transaction",
backend-python.md) followed, on approval only, by check-in code issuance
(hash persisted, plaintext handed to the encrypted outbox payload) and one
`outbox_messages` row (ADR-002), then the audit event.

Authorization (permission + host-ownership check) is the API layer's job
(app/api/visits.py, task 11) -- these functions assume the caller has
already been authorized and only enforce the state-machine invariant.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto.envelope import EnvelopeKeyProvider, encrypt_payload
from app.domain.audit import write_audit_event
from app.domain.rbac import PERMISSION_POLICY_VERSION
from app.domain.visits.guards import identity_verified_by_code, watchlist_clear
from app.domain.visits.state_machine import InvalidTransitionError, apply_transition
from app.models import OutboxMessage, Tenant, User, Visit

__all__ = [
    "InvalidTransitionError",
    "EmptyDenialReasonError",
    "InvalidCheckinCodeError",
    "approve_visit",
    "deny_visit",
    "checkin_visit",
    "dispatch_idempotency_key",
    "credential_grant_idempotency_key",
    "arrival_notify_idempotency_key",
]

# Placeholder pending a real product decision on pre-registration/check-in
# code validity windows (not specified by ADR-002 or the US-11 plan beyond
# "not_valid_after is populated") -- flagged here rather than silently
# invented and buried.
CHECKIN_CODE_VALIDITY = timedelta(days=7)

VISIT_REGISTERED_REASON = "host_approval"
# Coded audit reason for denial -- NEVER the host's free-text
# `visits.denial_reason` verbatim (US-11 review, Should-fix #2). The free
# text stays only on the purgeable `visits` row; the audit row instead
# carries this fixed code plus target_type/target_id pointing at the visit.
VISIT_DENIED_REASON_CODE = "host_denial"


class EmptyDenialReasonError(Exception):
    """Raised if deny_visit is called with a blank reason -- the API layer's
    DTO (VisitDenyRequest) already enforces this with Pydantic validation
    (422), but the domain service defends independently so no future
    caller that bypasses the DTO can persist a blank denial reason."""


class InvalidCheckinCodeError(Exception):
    """Raised for every check-in rejection cause (unknown hash, wrong
    tenant, expired, already consumed) -- ONE exception type, mapped to a
    single uniform 404 by the API layer (app/api/visits.py). Never
    subclassed per cause: distinguishing causes at any layer would leak
    validity information to the caller (US-01 plan, Part A Risks)."""


def dispatch_idempotency_key(visit_id: uuid.UUID) -> str:
    """Deterministic outbox idempotency key (ADR-002 §2): a visit can be
    approved exactly once, so exactly one dispatch message exists per
    visit -- a duplicate INSERT (e.g. a retried approval that somehow
    re-ran) is a UNIQUE-constraint no-op/conflict, never a second
    notification."""
    return hashlib.sha256(f"visit.checkin_code.dispatch:{visit_id}".encode()).hexdigest()


def credential_grant_idempotency_key(visit_id: uuid.UUID) -> str:
    """Deterministic (ADR-003): a visit can be checked in exactly once, so
    exactly one credential-grant command exists per visit."""
    return hashlib.sha256(f"visit.credential_grant.command:{visit_id}".encode()).hexdigest()


def arrival_notify_idempotency_key(visit_id: uuid.UUID) -> str:
    """Deterministic (ADR-003): one host-arrival notification per visit."""
    return hashlib.sha256(f"visit.arrival.notify:{visit_id}".encode()).hexdigest()


async def _load_visit_after_guarded_update(session: AsyncSession, tenant_id: uuid.UUID, visit_id: uuid.UUID) -> Visit:
    return (
        await session.execute(select(Visit).where(Visit.id == visit_id, Visit.tenant_id == tenant_id))
    ).scalar_one()


async def approve_visit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    visit_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    key_provider: EnvelopeKeyProvider,
) -> Visit:
    """Requested -> Registered. Raises InvalidTransitionError if the visit
    is not currently Requested (0 rows affected by the guarded UPDATE) --
    the API layer maps this to 409 (US-11 review, Should-fix #6)."""
    to_status = apply_transition("Requested", "host_approval")

    result = await session.execute(
        update(Visit)
        .where(Visit.id == visit_id, Visit.tenant_id == tenant_id, Visit.status == "Requested")
        .values(status=to_status, decided_by_user_id=actor_user_id, decided_at=datetime.now(timezone.utc))
    )
    if result.rowcount == 0:
        raise InvalidTransitionError("visit is not in Requested status")

    visit = await _load_visit_after_guarded_update(session, tenant_id, visit_id)

    checkin_code = secrets.token_urlsafe(24)
    visit.checkin_code_hash = hashlib.sha256(checkin_code.encode()).hexdigest()
    code_expires_at = datetime.now(timezone.utc) + CHECKIN_CODE_VALIDITY
    # Persisted here (US-01, task 2) so the check-in domain layer can read
    # `within_visit_window` off this row alone -- previously this value only
    # ever reached outbox_messages.not_valid_after (a dispatch artifact).
    visit.checkin_code_expires_at = code_expires_at

    tenant_name = (
        await session.execute(select(Tenant.name).where(Tenant.id == tenant_id))
    ).scalar_one()

    payload = {
        "schema_version": "1",
        "tenant_id": str(tenant_id),
        "visit_id": str(visit_id),
        "correlation_id": str(visit.correlation_id),
        "idempotency_key": dispatch_idempotency_key(visit_id),
        "contact_channel": visit.contact_channel,
        "contact_value": visit.contact_value,
        "checkin_code": checkin_code,
        "tracking_reference": visit.tracking_reference,
        "code_expires_at": code_expires_at.isoformat(),
        "tenant_display_name": tenant_name,
    }
    encrypted = encrypt_payload(json.dumps(payload).encode(), key_provider)

    outbox = OutboxMessage(
        tenant_id=tenant_id,
        message_type="visit.checkin_code.dispatch",
        aggregate_type="visit",
        aggregate_id=visit_id,
        correlation_id=visit.correlation_id,
        idempotency_key=dispatch_idempotency_key(visit_id),
        payload=encrypted.ciphertext,
        payload_key_ref=encrypted.key_ref,
        status="pending",
        not_valid_after=code_expires_at,
    )
    session.add(outbox)
    await session.flush()

    await write_audit_event(
        session,
        tenant_id=tenant_id,
        event_type="visit.registered",
        actor=str(actor_user_id),
        target_type="visit",
        target_id=visit_id,
        reason=VISIT_REGISTERED_REASON,
        correlation_id=visit.correlation_id,
        policy_version=PERMISSION_POLICY_VERSION,
    )

    return visit


async def deny_visit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    visit_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str,
) -> Visit:
    """Requested -> Denied. `reason` (free text, may contain visitor PII) is
    stored only on the purgeable `visits.denial_reason` column -- the
    append-only `visit.denied` audit event carries a coded reason +
    visits.id reference instead, never the free text verbatim (US-11
    review, Should-fix #2)."""
    if not reason or not reason.strip():
        raise EmptyDenialReasonError("reason must not be empty")

    to_status = apply_transition("Requested", "host_denial")

    result = await session.execute(
        update(Visit)
        .where(Visit.id == visit_id, Visit.tenant_id == tenant_id, Visit.status == "Requested")
        .values(
            status=to_status,
            denial_reason=reason,
            decided_by_user_id=actor_user_id,
            decided_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount == 0:
        raise InvalidTransitionError("visit is not in Requested status")

    visit = await _load_visit_after_guarded_update(session, tenant_id, visit_id)

    await write_audit_event(
        session,
        tenant_id=tenant_id,
        event_type="visit.denied",
        actor=str(actor_user_id),
        target_type="visit",
        target_id=visit_id,
        reason=VISIT_DENIED_REASON_CODE,
        correlation_id=visit.correlation_id,
        policy_version=PERMISSION_POLICY_VERSION,
    )

    return visit


VISIT_CHECKED_IN_REASON = "qr"
# Coded stand-in for visit-lifecycle.yaml's `verification_method` audit
# field (US-01 plan, Part A Risks -- audit-schema debt, not a permanent
# convention): audit_events has no verification_method column, and this
# story's only method is QR-code possession, so `reason` carries it,
# disambiguated from a denial's coded reason by event_type="visit.checked_in".


async def checkin_visit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    checkin_code: str,
    actor_user_id: uuid.UUID,
    key_provider: EnvelopeKeyProvider,
) -> Visit:
    """Registered -> CheckedIn (US-01, task 5). Raises InvalidCheckinCodeError
    for every rejection cause -- unknown hash, wrong tenant, expired code,
    already-consumed code -- uniformly; the API layer maps this to one 404
    (never distinguishable, per Part A Risks' anti-enumeration reasoning).

    The guarded UPDATE folds `within_visit_window` (`checkin_code_expires_at
    > now`) into the SAME `WHERE` clause as the hash/tenant/status
    predicates, rather than checking expiry as a separate step after the
    row is flipped -- an expired-but-real code must behave identically
    (zero rows matched, no flip, no rollback) to an unknown/wrong-tenant
    code, closing the timing/behavior oracle both design-gate reviews
    independently flagged. A NULL `checkin_code_expires_at` fails closed for
    free here (`NULL > :now` is never true in SQL).

    `identity_verified_by_code`/`watchlist_clear` are called explicitly
    (not inlined) so each guard has exactly one call site a later story
    replaces -- watchlist_clear is a deliberate always-True stub (see
    app.domain.visits.guards)."""
    # Return values intentionally unchecked -- both always return True today
    # (US-01 review, Should-fix: guard results are discarded). This is safe
    # ONLY because there is no real watchlist yet. A future watchlist story
    # must NOT simply flip watchlist_clear() to sometimes return False and
    # branch on it here -- a real watchlist match must route through the
    # separate Registered -> Held (watchlist_match) transition for
    # authorized human review (no automated denial, security-privacy.md),
    # never fail this transition directly. Rewire the call site, don't just
    # flip the return value.
    identity_verified_by_code()
    watchlist_clear()

    now = datetime.now(timezone.utc)
    code_hash = hashlib.sha256(checkin_code.encode()).hexdigest()
    to_status = apply_transition("Registered", "checkin_verified")

    result = await session.execute(
        update(Visit)
        .where(
            Visit.tenant_id == tenant_id,
            Visit.status == "Registered",
            Visit.checkin_code_hash == code_hash,
            Visit.checkin_code_expires_at > now,
        )
        .values(status=to_status, checked_in_by_user_id=actor_user_id, checked_in_at=now)
    )
    if result.rowcount == 0:
        raise InvalidCheckinCodeError("invalid or expired check-in code")

    # Reload scoped by status="CheckedIn" too (US-01 review, Note) -- belt-
    # and-suspenders on top of the guarded UPDATE above, not a new guarantee
    # (checkin_code_hash collision on a 192-bit token is already negligible).
    visit = (
        await session.execute(
            select(Visit).where(
                Visit.tenant_id == tenant_id,
                Visit.checkin_code_hash == code_hash,
                Visit.status == "CheckedIn",
            )
        )
    ).scalar_one()

    host_email = (
        await session.execute(
            select(User.email).where(User.id == visit.host_user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one()

    # Credential-grant command (ADR-003): cloud-recorded intent only, no
    # consumer yet (apps/edge-connector is still a scaffold). No PII --
    # opaque IDs + a time window only. `site_id`/`device_id` stay `null`;
    # no `zone` field in the canonical envelope (US-01 plan Scope amendment
    # follow-on / ADR-003). Encrypted uniformly with every other
    # outbox_messages row (ADR-002 §5) even though this payload has no PII.
    grant_payload = {
        "schema_version": "1",
        "tenant_id": str(tenant_id),
        "visit_id": str(visit.id),
        "correlation_id": str(visit.correlation_id),
        "idempotency_key": credential_grant_idempotency_key(visit.id),
        "expiry": visit.checkin_code_expires_at.isoformat(),
        "site_id": None,
        "device_id": None,
    }
    grant_encrypted = encrypt_payload(json.dumps(grant_payload).encode(), key_provider)
    session.add(
        OutboxMessage(
            tenant_id=tenant_id,
            message_type="visit.credential_grant.command",
            aggregate_type="visit",
            aggregate_id=visit.id,
            correlation_id=visit.correlation_id,
            idempotency_key=credential_grant_idempotency_key(visit.id),
            payload=grant_encrypted.ciphertext,
            payload_key_ref=grant_encrypted.key_ref,
            status="pending",
            not_valid_after=visit.checkin_code_expires_at,
        )
    )

    # Host-arrival notification intent (delivery is the not-yet-built relay
    # worker's job, same scope cut US-11 made for visit.checkin_code.dispatch).
    # PII (host_email, visitor_full_name) -- envelope-encrypted.
    notify_payload = {
        "schema_version": "1",
        "tenant_id": str(tenant_id),
        "visit_id": str(visit.id),
        "correlation_id": str(visit.correlation_id),
        "idempotency_key": arrival_notify_idempotency_key(visit.id),
        "host_user_id": str(visit.host_user_id),
        "host_email": host_email,
        "visitor_full_name": visit.visitor_full_name,
        "tracking_reference": visit.tracking_reference,
    }
    notify_encrypted = encrypt_payload(json.dumps(notify_payload).encode(), key_provider)
    session.add(
        OutboxMessage(
            tenant_id=tenant_id,
            message_type="visit.arrival.notify",
            aggregate_type="visit",
            aggregate_id=visit.id,
            correlation_id=visit.correlation_id,
            idempotency_key=arrival_notify_idempotency_key(visit.id),
            payload=notify_encrypted.ciphertext,
            payload_key_ref=notify_encrypted.key_ref,
            status="pending",
        )
    )
    await session.flush()

    await write_audit_event(
        session,
        tenant_id=tenant_id,
        event_type="visit.checked_in",
        actor=str(actor_user_id),
        target_type="visit",
        target_id=visit.id,
        reason=VISIT_CHECKED_IN_REASON,
        correlation_id=visit.correlation_id,
        policy_version=PERMISSION_POLICY_VERSION,
    )

    return visit
