"""`outbox_messages` model (US-11, task 2, ADR-002 §1 exactly).

A single generic transactional-outbox table (the modular-monolith default --
one table, not one per message type). Tenant-scoped, RLS-enforced (ADR-001's
binding pattern). `payload` is envelope-encrypted ciphertext (BYTEA), never
cleartext JSONB -- it carries a live credential (the plaintext check-in
code) plus visitor PII (ADR-002 §5). Decrypted only transiently, in the
(not-yet-built) relay worker's memory.

`site_id`/`device_id` are reserved-nullable for the later edge-connector
device-command variant (ADR-002 §1, "This message is a notification, not a
panel command") -- not applicable to `visit.checkin_code.dispatch`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

OUTBOX_STATUSES = ("pending", "dispatched", "failed")


class OutboxMessage(Base):
    """Dispatch-intent row written atomically with a state transition (ADR-002 §1)."""

    __tablename__ = "outbox_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    # Envelope-encrypted ciphertext (app/crypto/envelope.py) -- NOT cleartext
    # JSONB (ADR-002 §5). payload_key_ref records the key/version used, to
    # support Key Vault key rotation.
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_key_ref: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Copy of the code's code_expires_at -- the staleness send-gate (ADR-002
    # §4) reads this WITHOUT decrypting the payload.
    not_valid_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Reserved for the later edge-connector device-command variant; not
    # applicable to a visitor notification (ADR-002 §1).
    site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'dispatched', 'failed')", name="ck_outbox_messages_status"
        ),
        Index("ix_outbox_messages_tenant_id", "tenant_id"),
    )
