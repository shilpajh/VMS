"""`portal_contact_verifications` model (US-13a, ADR-004).

Ephemeral, tenant-scoped, RLS-enforced (ADR-001's binding pattern, reused
verbatim). Holds an OTP (as a keyed HMAC hash -- app/crypto/hmac_hash.py --
NEVER the plaintext) and, once the OTP verifies, a verification-token hash.
Rows are short-lived: consumed (deleted) on a successful submission; the
ops-role retention job purges abandoned/expired rows (ADR-004).

`otp_hash`/`verification_token_hash` are HMAC-SHA256, not bare SHA-256: a
6-digit OTP has only 10^6 preimages and a bare hash would be instantly
reversible if leaked (unlike the check-in code's ~192-bit token, which US-01
could safely bare-hash). See app/crypto/hmac_hash.py and US-13 review
Should-fix #3.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PortalContactVerification(Base):
    """One OTP-verification lifecycle row per `otp/request` call."""

    __tablename__ = "portal_contact_verifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    contact_channel: Mapped[str] = mapped_column(String(16), nullable=False)
    contact_value: Mapped[str] = mapped_column(String(320), nullable=False)

    # --- OTP (keyed HMAC hash only, never plaintext) ---
    otp_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    otp_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    otp_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Set true when a newer otp/request for the same (tenant, channel, value)
    # arrives -- so exactly one "current" OTP exists per contact and the
    # 5-attempt cap is per-contact, not per-row (ADR-004).
    superseded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # --- Consent captured here, ahead of the OTP send (US-13a decision 3) ---
    privacy_notice_acknowledged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    privacy_notice_version: Mapped[str] = mapped_column(String(32), nullable=False)

    # --- Verification token (issued on OTP verify; consumed on submission) ---
    verification_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verification_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("contact_channel IN ('email', 'sms')", name="ck_pcv_contact_channel"),
        Index("ix_pcv_tenant_channel_value", "tenant_id", "contact_channel", "contact_value"),
        Index("ix_pcv_verification_token_hash", "verification_token_hash"),
    )
