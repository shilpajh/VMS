import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditEvent(Base):
    """Append-only audit sink (ADR-001 §2). Owned by the Audit & Reporting
    module; introduced here because identity/tenancy actions must produce
    durable audit evidence from day one. Written to by many modules by
    design — an intentional shared sink, not a module-boundary blur.

    Never UPDATEd/DELETEd (enforced at the DB grant level, not just by
    convention) and not subject to the user-PII purge (ADR-001,
    Consequences / Security and privacy impact).

    `tenant_id` is NEVER nullable: platform-level events (e.g.
    `tenant.created`) are attributed to the reserved sentinel `platform`
    tenant row, so there is no nullable tenant marker anywhere.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    # Only populated for role-change events; NULL otherwise (ADR-001 §3/§9).
    policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_audit_events_tenant_id", "tenant_id"),)
