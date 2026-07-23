"""Public, unauthenticated portal submission endpoint (US-11, task 9).

`POST /public/portal/{tenant_slug}/visit-requests`. Exact order, binding
(US-11 plan/API contract delta, review Notes):

  1. CAPTCHA verify -- BEFORE any DB work, BEFORE tenant-slug resolution
     (avoids a slug-validity timing oracle).
  2. Rate limit check (per-IP + per-tenant-slug, keyed on the raw path
     slug string -- no tenant DB lookup needed yet).
  3. Tenant resolution (`SET LOCAL app.current_tenant_id`).
  4. Idempotency-Key dedup check (tenant-scoped, post-GUC, bound to BOTH the
     client's actual header value AND submission content -- see
     `_submission_dedup_key`'s docstring; US-11 verify-story remediation).
  5. Privacy-notice-acknowledgment required (422 if false/missing).
  6. Create the Requested visit (host resolution by exact match; unresolved
     -> host_user_id stays NULL).
  7. `visit.requested` audit (actor="portal").
  8. Uniform 202 + tracking_reference, regardless of host resolution.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dtos.visits import PortalVisitRequestAccepted, PortalVisitRequestCreate
from app.auth.public_tenant import resolve_public_tenant
from app.config import settings
from app.db.session import get_session
from app.domain.audit import write_audit_event
from app.domain.visits.tracking_reference import assign_unique_tracking_reference
from app.models import User, Visit
from app.security.captcha import TurnstileVerifier, get_captcha_verifier
from app.security.rate_limit import (
    TokenBucketRateLimiter,
    get_per_ip_rate_limiter,
    get_per_tenant_rate_limiter,
    resolve_client_ip,
)

router = APIRouter()

VISIT_REQUESTED_REASON = "portal_submission"
PORTAL_ACTOR = "portal"


def _submission_dedup_key(idempotency_key: str, contact_value: str, host_hint: str | None) -> str:
    # Bound to BOTH the client's actual Idempotency-Key header value AND
    # submission content (US-11 verify-story remediation, Track 2 item 3).
    #
    # Content-hashed alone (the original US-11 review, Should-fix #1
    # mitigation) is NOT sufficient: it makes the header's *value*
    # irrelevant and the *content* the entire secret. contact_value and
    # host_hint are frequently guessable/enumerable (e.g. a corporate email
    # in a predictable format, a host's name from a LinkedIn post), so an
    # attacker who reproduces the victim's content -- with an arbitrary
    # Idempotency-Key of their own choosing, never the victim's real one --
    # could fish out the victim's real tracking_reference
    # (test_portal_dedup_cross_actor_leak.py demonstrated this live, not
    # theoretically).
    #
    # Binding the hash to the actual header value closes this: a resubmission
    # only dedups if the client supplies the SAME key AND the SAME content.
    # An attacker who doesn't know the victim's real Idempotency-Key value
    # cannot produce a matching hash no matter how well they guess the
    # content.
    material = f"{idempotency_key}\x1f{contact_value}\x1f{host_hint or ''}"
    return hashlib.sha256(material.encode()).hexdigest()


async def _resolve_host_user_id(
    session: AsyncSession, tenant_id: uuid.UUID, host_hint: str | None
) -> uuid.UUID | None:
    if not host_hint:
        return None
    result = await session.execute(
        select(User.id).where(
            User.tenant_id == tenant_id,
            (User.email == host_hint) | (User.display_name == host_hint),
        )
    )
    row = result.first()
    return row[0] if row else None


@router.post(
    "/public/portal/{tenant_slug}/visit-requests",
    response_model=PortalVisitRequestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_portal_visit_request(
    tenant_slug: str,
    body: PortalVisitRequestCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    captcha_verifier: TurnstileVerifier = Depends(get_captcha_verifier),
    per_ip_limiter: TokenBucketRateLimiter = Depends(get_per_ip_rate_limiter),
    per_tenant_limiter: TokenBucketRateLimiter = Depends(get_per_tenant_rate_limiter),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PortalVisitRequestAccepted:
    client_ip = resolve_client_ip(
        remote_addr=request.client.host if request.client else None,
        x_forwarded_for=request.headers.get("x-forwarded-for"),
        trust_forwarded_for=settings.trust_forwarded_for,
    )

    # 1. CAPTCHA verify -- before any DB work, before tenant-slug resolution.
    if not await captcha_verifier.verify(body.turnstile_token, remote_ip=client_ip):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="captcha verification failed")

    # 2. Rate limiting -- per-IP + per-tenant-slug, pre-DB.
    if not await per_ip_limiter.check(client_ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded")
    if not await per_tenant_limiter.check(tenant_slug):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded")

    # 3. Tenant resolution -- SET LOCAL before any tenant-scoped query.
    tenant = await resolve_public_tenant(tenant_slug, session=session)

    # 4. Idempotency-Key dedup -- tenant-scoped (post-GUC), bound to BOTH the
    # actual client-supplied header value and submission content.
    dedup_key = (
        _submission_dedup_key(idempotency_key, body.contact_value, body.host_hint)
        if idempotency_key
        else None
    )
    if dedup_key is not None:
        existing = (
            await session.execute(
                select(Visit).where(
                    Visit.tenant_id == tenant.id, Visit.submission_dedup_key == dedup_key
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return PortalVisitRequestAccepted(tracking_reference=existing.tracking_reference)

    # 5. Privacy notice acknowledgment required.
    if not body.privacy_notice_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="privacy notice acknowledgment required",
        )

    # 6. Create the Requested visit. Host resolution never blocks/branches
    # the response -- unresolved host_hint stays NULL (anti-enumeration).
    host_user_id = await _resolve_host_user_id(session, tenant.id, body.host_hint)
    correlation_id = uuid.uuid4()

    visit = Visit(
        tenant_id=tenant.id,
        status="Requested",
        visitor_full_name=body.visitor_full_name,
        contact_channel=body.contact_channel,
        contact_value=body.contact_value,
        host_hint=body.host_hint,
        host_user_id=host_user_id,
        privacy_notice_acknowledged=True,
        privacy_notice_version=body.privacy_notice_version,
        submission_dedup_key=dedup_key,
        correlation_id=correlation_id,
    )
    await assign_unique_tracking_reference(session, visit)

    # 7. visit.requested audit (actor="portal" -- no authenticated human
    # actor exists for an anonymous submission).
    await write_audit_event(
        session,
        tenant_id=tenant.id,
        event_type="visit.requested",
        actor=PORTAL_ACTOR,
        target_type="visit",
        target_id=visit.id,
        reason=VISIT_REQUESTED_REASON,
        correlation_id=correlation_id,
    )

    # 8. Uniform 202 + tracking_reference -- never host/other visit data.
    return PortalVisitRequestAccepted(tracking_reference=visit.tracking_reference)
