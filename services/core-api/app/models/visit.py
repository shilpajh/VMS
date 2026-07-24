"""`visits` model (US-11, task 2).

Tenant-scoped, RLS-enforced (ADR-001's binding pattern, reused verbatim).
Implements the canonical visit-lifecycle status enum
(`packages/contracts/statemachine/visit-lifecycle.yaml`) even though this
story only wires `Requested -> {Registered, Denied}` -- the CHECK constraint
covers the full lifecycle so later stories extending the state machine never
need a migration just to widen this column's allowed values.

`host_user_id` is nullable (a portal submission whose `host_hint` doesn't
resolve to a known user stays unassigned -- US-11 Part A, "no reception-
triage UI for NULL-host visits" is an explicit, deferred, non-silent scope
cut) with a composite FK `(host_user_id, tenant_id) -> users(id, tenant_id)`
mirroring `user_roles`' composite FK (ADR-001 §2): NULL is exempt (Postgres
MATCH SIMPLE), any non-NULL value is structurally forced to belong to the
same tenant.

`checkin_code_hash` stores ONLY the SHA-256 hash of the `secrets.
token_urlsafe(24)` check-in code (US-11 review, Should-fix #4) -- the
plaintext is never persisted here, only transiently generated and handed to
the encrypted outbox payload (app/crypto/envelope.py).

`denial_reason` is free text and MAY contain visitor PII -- it lives only on
this purgeable row, never verbatim in the append-only `audit_events` table
(US-11 review, Should-fix #2; see app/domain/visits/service.py).

`submission_dedup_key` backs the public portal's tenant-scoped
`Idempotency-Key` dedup. Originally (US-11 review, Should-fix #1) a SHA-256
hash of submission content alone (contact_value + host_hint) -- but
`/verify-story` (Track 2, item 3) proved that content-only hashing let an
attacker who guesses a victim's contact_value+host_hint supply their OWN
arbitrary Idempotency-Key and still retrieve the victim's real
tracking_reference, since the header's actual value was never checked, only
its presence. Fixed in the US-11 remediation cycle: the hash is now a
SHA-256 of the client's ACTUAL Idempotency-Key header value combined with
submission content (see `app/api/portal.py::_submission_dedup_key`), so a
resubmission only dedups when both the same key value AND the same content
are supplied -- guessing content alone is no longer sufficient. NULL for
submissions made without an `Idempotency-Key` header (multiple NULLs are
permitted by a unique index -- standard Postgres semantics).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Full canonical lifecycle (packages/contracts/statemachine/visit-lifecycle.yaml).
# Only Requested/Registered/Denied are reachable via this story's own code;
# the rest are reserved for later stories' transitions.
VISIT_STATUSES = (
    "Requested",
    "Registered",
    "AwaitingApproval",
    "AwaitingDualSignoff",
    "Held",
    "CheckedIn",
    "CheckedOut",
    "Denied",
    "Safe",
)

CONTACT_CHANNELS = ("email", "sms")


class Visit(Base):
    """A single visitor pre-registration / visit lifecycle record."""

    __tablename__ = "visits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="Requested", server_default="Requested"
    )

    # --- Visitor-submitted data (PII) ---
    visitor_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_channel: Mapped[str] = mapped_column(String(16), nullable=False)
    contact_value: Mapped[str] = mapped_column(String(320), nullable=False)
    host_hint: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Host resolution/assignment ---
    host_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # --- Tracking / credential ---
    tracking_reference: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    checkin_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Check-in (US-01) ---
    # Persisted copy of the value already computed transiently in
    # approve_visit and copied onto outbox_messages.not_valid_after -- lets
    # the check-in domain layer enforce `within_visit_window` by reading
    # this row alone, never outbox_messages (a dispatch artifact, not the
    # domain's source of truth). A known-interim substitution for a real
    # scheduled-arrival-window field -- see US-01 plan, Part A Risks.
    checkin_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    checked_in_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Denial ---
    denial_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Consent / privacy notice (US-11 review, Should-fix #8 placeholder) ---
    privacy_notice_acknowledged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    privacy_notice_version: Mapped[str] = mapped_column(String(32), nullable=False)

    # --- Portal submission detail (US-13a; PRD 3.1) ---
    # All nullable (existing visits predate them). `group_type='group'` with
    # `expected_group_size` makes a group visit's head-count visible to
    # muster/`Safe` accounting even though per-member records are a later
    # story (US-13a plan, Risks). `contact_verified` records whether the
    # visit was created via a validated OTP verification token -- a non-PII
    # trust property (never the contact_value itself).
    purpose: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    expected_group_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    identity_verification_choice: Mapped[str | None] = mapped_column(String(16), nullable=True)
    contact_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # --- Public-submission anti-replay dedup (US-11 review, Should-fix #1) ---
    submission_dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Traceability / decision metadata ---
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ("
            + ", ".join(f"'{s}'" for s in VISIT_STATUSES)
            + ")",
            name="ck_visits_status",
        ),
        CheckConstraint(
            "contact_channel IN ('email', 'sms')", name="ck_visits_contact_channel"
        ),
        CheckConstraint(
            "group_type IS NULL OR group_type IN ('individual', 'group')",
            name="ck_visits_group_type",
        ),
        CheckConstraint(
            "identity_verification_choice IS NULL OR "
            "identity_verification_choice IN ('upload_now', 'send_to_host')",
            name="ck_visits_identity_verification_choice",
        ),
        ForeignKeyConstraint(
            ["host_user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_visits_host_user_tenant",
        ),
        ForeignKeyConstraint(
            ["checked_in_by_user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_visits_checked_in_by_user_tenant",
        ),
        UniqueConstraint(
            "tenant_id", "submission_dedup_key", name="uq_visits_tenant_dedup_key"
        ),
        Index("ix_visits_tenant_id", "tenant_id"),
        Index("ix_visits_host_user_id", "host_user_id"),
        Index("ix_visits_checked_in_by_user_id", "checked_in_by_user_id"),
    )
