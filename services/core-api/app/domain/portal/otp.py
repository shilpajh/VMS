"""Portal OTP contact-verification domain logic (US-13a, ADR-004).

The security-critical core, kept out of the API layer so it is testable in
isolation (mirrors app/domain/visits/tracking_reference.py's one-concern
scope). All functions assume the caller has already set the tenant GUC
(`resolve_public_tenant`) and passes a validated `tenant_id`.

Discipline reused from US-01's check-in code:
- OTP + verification token hashed at rest, never persisted plaintext
  (here keyed HMAC, not bare SHA-256 -- see app/crypto/hmac_hash.py).
- Single-use via a race-safe guarded UPDATE/DELETE (affected-row count),
  never a check-then-act.
- One uniform error per class (InvalidOtpError / InvalidVerificationTokenError)
  so no rejection cause is distinguishable to a caller.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto.hmac_hash import HmacKeyProvider, hmac_hash, verify_hmac
from app.models import PortalContactVerification

__all__ = [
    "InvalidOtpError",
    "InvalidVerificationTokenError",
    "generate_otp_code",
    "issue_otp",
    "verify_otp_and_issue_token",
    "consume_verification_token",
]

# A fixed non-matching HMAC digest used to keep the verify path constant-work
# when no pending OTP row exists (US-13 review Should-fix #4): we still run an
# HMAC compare against this sentinel so "no pending OTP" does the same work as
# "wrong code", rather than short-circuiting on the missing row.
_SENTINEL_DIGEST = "0" * 64


class InvalidOtpError(Exception):
    """Uniform OTP-verify failure: no pending OTP / wrong code / expired /
    attempts exhausted -- never distinguished (API maps to one 400)."""


class InvalidVerificationTokenError(Exception):
    """Uniform verification-token failure: unknown / expired / already
    consumed / wrong contact -- never distinguished (API maps to 422)."""


def generate_otp_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def _generate_verification_token() -> str:
    # Same high-entropy bearer-token idiom as the US-01 check-in code.
    return secrets.token_urlsafe(24)


async def issue_otp(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    contact_channel: str,
    contact_value: str,
    privacy_notice_version: str,
    hmac_provider: HmacKeyProvider,
) -> tuple[PortalContactVerification, str]:
    """Supersedes any prior unconsumed rows for this
    `(tenant, channel, contact_value)`, then creates a fresh OTP row.
    Returns `(row, plaintext_code)` -- the plaintext exists only to be
    handed to the encrypted dispatch payload, never persisted."""
    # Supersede prior rows so exactly one current OTP exists per contact --
    # the 5-attempt cap is then per-contact, not per-row (ADR-004).
    await session.execute(
        update(PortalContactVerification)
        .where(
            PortalContactVerification.tenant_id == tenant_id,
            PortalContactVerification.contact_channel == contact_channel,
            PortalContactVerification.contact_value == contact_value,
            PortalContactVerification.consumed_at.is_(None),
            PortalContactVerification.superseded.is_(False),
        )
        .values(superseded=True)
    )

    code = generate_otp_code()
    row = PortalContactVerification(
        tenant_id=tenant_id,
        contact_channel=contact_channel,
        contact_value=contact_value,
        otp_hash=hmac_hash(code, hmac_provider),
        otp_expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.otp_ttl_seconds),
        privacy_notice_acknowledged=True,
        privacy_notice_version=privacy_notice_version,
    )
    session.add(row)
    await session.flush()
    return row, code


async def _current_row(
    session: AsyncSession, tenant_id: uuid.UUID, contact_channel: str, contact_value: str
) -> PortalContactVerification | None:
    """The single current (non-superseded, non-consumed) OTP row for this
    contact, if any -- verify always resolves against exactly this one."""
    return (
        await session.execute(
            select(PortalContactVerification).where(
                PortalContactVerification.tenant_id == tenant_id,
                PortalContactVerification.contact_channel == contact_channel,
                PortalContactVerification.contact_value == contact_value,
                PortalContactVerification.superseded.is_(False),
                PortalContactVerification.consumed_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def verify_otp_and_issue_token(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    contact_channel: str,
    contact_value: str,
    otp_code: str,
    hmac_provider: HmacKeyProvider,
) -> str:
    """Constant-work verify: always fetch the current row, always run an
    HMAC compare (against a sentinel if no row/expired/exhausted), so the
    four failure causes are indistinguishable by timing, not only by the
    uniform InvalidOtpError. On success, issues + persists a verification
    token (hashed) and returns the plaintext token."""
    now = datetime.now(timezone.utc)
    row = await _current_row(session, tenant_id, contact_channel, contact_value)

    usable = (
        row is not None
        and row.otp_expires_at > now
        and row.otp_attempts < settings.otp_max_attempts
    )
    expected_digest = row.otp_hash if (row is not None and usable) else _SENTINEL_DIGEST
    matched = verify_hmac(otp_code, expected_digest, hmac_provider)

    if not (usable and matched):
        # Constant-work failure path: ALWAYS run one attempt-increment UPDATE
        # of identical shape, so "no pending OTP", "wrong code", "expired",
        # and "attempts exhausted" all do SELECT + one UPDATE + one HMAC
        # compare -- no observable work differential (US-13 review
        # Should-fix #4). The UPDATE targets a real usable row (burning a
        # guess) or a non-matching sentinel id (affecting nothing) with the
        # same WHERE shape either way; race-safe on the attempt count.
        target_id = row.id if (row is not None and usable) else uuid.uuid4()
        await session.execute(
            update(PortalContactVerification)
            .where(PortalContactVerification.id == target_id)
            .values(otp_attempts=PortalContactVerification.otp_attempts + 1)
        )
        raise InvalidOtpError("invalid or expired code")

    token = _generate_verification_token()
    row.verification_token_hash = hmac_hash(token, hmac_provider)
    row.verification_token_expires_at = now + timedelta(
        seconds=settings.verification_token_ttl_seconds
    )
    await session.flush()
    return token


async def consume_verification_token(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    contact_channel: str,
    contact_value: str,
    verification_token: str,
    hmac_provider: HmacKeyProvider,
) -> str:
    """Single-use consume, scoped to the exact `(tenant, channel,
    contact_value)` the token was issued against. Race-safe: a guarded
    UPDATE stamps `consumed_at` only if it is still NULL and unexpired;
    rowcount 0 -> already consumed / expired / mismatch -> uniform error.
    Returns the row's `privacy_notice_version` (copied onto the visit)."""
    now = datetime.now(timezone.utc)
    token_hash = hmac_hash(verification_token, hmac_provider)

    result = await session.execute(
        update(PortalContactVerification)
        .where(
            PortalContactVerification.tenant_id == tenant_id,
            PortalContactVerification.contact_channel == contact_channel,
            PortalContactVerification.contact_value == contact_value,
            PortalContactVerification.verification_token_hash == token_hash,
            PortalContactVerification.consumed_at.is_(None),
            PortalContactVerification.verification_token_expires_at > now,
        )
        .values(consumed_at=now)
        .returning(PortalContactVerification.privacy_notice_version)
    )
    row = result.first()
    if row is None:
        raise InvalidVerificationTokenError("invalid or expired verification token")
    return row[0]
