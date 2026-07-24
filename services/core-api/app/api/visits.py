"""Host/reception visit API routes (US-11, task 11).

Every tenant-scoped route returns 403 on a tenant mismatch or an
unauthorized ownership check (never 404) -- same contract US-10 established
for identity.py, extended here to visits: `GET /visits/{id}` is uniform 403
whether the row belongs to another tenant or doesn't exist at all, so
cross-tenant existence is never an oracle (US-11 review, Part A Risks).

`POST /visits/{id}/approve`/`deny` requires `approve_deny_visits` AND
`visit.host_user_id == principal.user_id` -- only the assigned host may
decide a visit (a NULL/unresolved host_user_id can never match any
principal, so those visits are correctly unreachable here; the deferred
reception-triage surface for them is an explicit, non-silent scope cut,
Part A).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dtos.visits import VisitCheckinRequest, VisitDenyRequest, VisitOut
from app.auth.dependencies import Principal, get_current_principal
from app.crypto.envelope import EnvelopeKeyProvider, get_envelope_key_provider
from app.db.session import get_session
from app.domain.rbac import has_permission
from app.domain.visits.service import (
    EmptyDenialReasonError,
    InvalidCheckinCodeError,
    InvalidTransitionError,
    approve_visit,
    checkin_visit,
    deny_visit,
)
from app.models import Visit

router = APIRouter()

_FORBIDDEN_DETAIL = "forbidden"
# One uniform detail string across every check-in rejection cause (unknown
# hash, wrong tenant, expired, already consumed) -- never distinguishable,
# per the US-01 plan's anti-enumeration reasoning.
_INVALID_CHECKIN_CODE_DETAIL = "invalid or expired check-in code"


async def _require_permission(session: AsyncSession, principal: Principal, permission_code: str) -> None:
    if not await has_permission(session, principal.tenant_id, principal.user_id, permission_code):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL)


async def _load_owned_visit_for_decision(
    session: AsyncSession, principal: Principal, visit_id: uuid.UUID
) -> Visit:
    """Uniform 403 whether the visit doesn't exist, belongs to another
    tenant, or isn't assigned to this principal -- never a 404, so none of
    those cases can be distinguished by a caller (anti-enumeration)."""
    visit = (
        await session.execute(
            select(Visit).where(Visit.id == visit_id, Visit.tenant_id == principal.tenant_id)
        )
    ).scalar_one_or_none()
    if visit is None or visit.host_user_id != principal.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL)
    return visit


@router.post("/visits/{visit_id}/approve", response_model=VisitOut)
async def approve_visit_route(
    visit_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    key_provider: EnvelopeKeyProvider = Depends(get_envelope_key_provider),
) -> Visit:
    await _require_permission(session, principal, "approve_deny_visits")
    await _load_owned_visit_for_decision(session, principal, visit_id)

    try:
        return await approve_visit(
            session,
            tenant_id=principal.tenant_id,
            visit_id=visit_id,
            actor_user_id=principal.user_id,
            key_provider=key_provider,
        )
    except InvalidTransitionError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="visit is not in Requested status"
        ) from None


@router.post("/visits/{visit_id}/deny", response_model=VisitOut)
async def deny_visit_route(
    visit_id: uuid.UUID,
    body: VisitDenyRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> Visit:
    await _require_permission(session, principal, "approve_deny_visits")
    await _load_owned_visit_for_decision(session, principal, visit_id)

    try:
        return await deny_visit(
            session,
            tenant_id=principal.tenant_id,
            visit_id=visit_id,
            actor_user_id=principal.user_id,
            reason=body.reason,
        )
    except InvalidTransitionError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="visit is not in Requested status"
        ) from None
    except EmptyDenialReasonError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="reason must not be empty"
        ) from None


@router.get("/visits", response_model=list[VisitOut])
async def list_visits(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[Visit]:
    """A `view_visits` holder (reception_security/tenant_admin) sees the
    full tenant-scoped list; a host without it sees only visits assigned to
    them (US-11 review, Should-fix #7)."""
    if await has_permission(session, principal.tenant_id, principal.user_id, "view_visits"):
        stmt = select(Visit).where(Visit.tenant_id == principal.tenant_id)
    else:
        stmt = select(Visit).where(
            Visit.tenant_id == principal.tenant_id, Visit.host_user_id == principal.user_id
        )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("/visits/checkin", response_model=VisitOut)
async def checkin_visit_route(
    body: VisitCheckinRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
    key_provider: EnvelopeKeyProvider = Depends(get_envelope_key_provider),
) -> Visit:
    """QR check-in (US-01). Registered here BEFORE `GET /visits/{visit_id}`
    even though the two never collide on method -- `/visits/checkin` has
    the same segment count as `/visits/{visit_id}`, and this ordering makes
    the exact-string route win deterministically rather than relying on
    Starlette's path-vs-param precedence. Gated on `checkin_confirm`
    (tenant-scoped only, no host-ownership check -- this is a
    reception/security action, not a host decision, unlike approve/deny)."""
    await _require_permission(session, principal, "checkin_confirm")

    try:
        return await checkin_visit(
            session,
            tenant_id=principal.tenant_id,
            checkin_code=body.checkin_code,
            actor_user_id=principal.user_id,
            key_provider=key_provider,
        )
    except InvalidCheckinCodeError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_INVALID_CHECKIN_CODE_DETAIL
        ) from None


@router.get("/visits/{visit_id}", response_model=VisitOut)
async def get_visit(
    visit_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> Visit:
    visit = (
        await session.execute(
            select(Visit).where(Visit.id == visit_id, Visit.tenant_id == principal.tenant_id)
        )
    ).scalar_one_or_none()
    if visit is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL)

    has_view = await has_permission(session, principal.tenant_id, principal.user_id, "view_visits")
    if not has_view and visit.host_user_id != principal.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL)

    return visit
