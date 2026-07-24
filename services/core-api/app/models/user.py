import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

USER_STATUSES = ("active", "disabled")


class User(Base):
    """Tenant-scoped staff user. SSO-only (Entra ID) — no passwords.

    `email`/`display_name` are PII: never logged (AGENTS.md, security-privacy.md).
    `external_idp_subject` stores the token `oid` claim (canonical), falling
    back to `sub` only when `oid` is absent (ADR-001 §5) — never mixed.

    `UNIQUE (id, tenant_id)` is redundant with the primary key but is a
    required prerequisite for the composite FK on `user_roles`
    `(user_id, tenant_id) -> users(id, tenant_id)` (ADR-001 §2, Risks).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    external_idp_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    # Retention reference for staff PII (US-07/ADR-005, DA-B1): set when the
    # user is disabled, cleared on re-enable. The purge scrubs a user whose
    # disabled_at is older than the staff_users window. `purged_at` marks an
    # already-scrubbed row so a re-run is idempotent (DA-S1).
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
        UniqueConstraint(
            "tenant_id", "external_idp_subject", name="uq_users_tenant_external_idp_subject"
        ),
        # Prerequisite for user_roles' composite FK — see docstring above.
        UniqueConstraint("id", "tenant_id", name="uq_users_id_tenant_id"),
        Index("ix_users_tenant_id", "tenant_id"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
    )
