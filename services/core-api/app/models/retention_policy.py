"""`retention_policies` model (US-07, ADR-005).

Per-tenant, per-data-category retention OVERRIDE. Absence of a row for a
(tenant, category) means the config default applies (app/domain/retention/
policy.py). Tenant-scoped, RLS-enforced (ADR-001's pattern) -- read by the
purge under the per-tenant GUC.

`data_category` -> table mapping (ADR-005): `staff_users`->users,
`visits`->visits, `outbox_messages`->outbox_messages,
`contact_verifications`->portal_contact_verifications.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

RETENTION_CATEGORIES = ("staff_users", "visits", "outbox_messages", "contact_verifications")


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    data_category: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "data_category IN ('staff_users', 'visits', 'outbox_messages', 'contact_verifications')",
            name="ck_retention_policies_category",
        ),
        CheckConstraint("retention_seconds > 0", name="ck_retention_policies_positive"),
        UniqueConstraint("tenant_id", "data_category", name="uq_retention_policies_tenant_category"),
        Index("ix_retention_policies_tenant_id", "tenant_id"),
    )
