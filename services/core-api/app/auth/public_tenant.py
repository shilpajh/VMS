"""Public (unauthenticated) tenant resolution for the portal endpoint
(US-11, task 6).

Mirrors app.auth.dependencies.get_current_principal's steps 1-2 exactly
(ADR-001 §1):
  1. Resolve tenant from the public, tenant-global `tenants` table -- no RLS
     involved (`tenants` is the discriminator source, not tenant-scoped).
  2. `SET LOCAL app.current_tenant_id` inside the request transaction,
     before any tenant-scoped query runs.

The difference from get_current_principal: there is no bearer token, no
`Principal`, no user at all -- this is a plain FastAPI dependency for the
public portal submission endpoint (app/api/portal.py), which has no
authenticated caller.

Unknown and suspended-tenant slugs return the exact same 404 (same status
code AND same detail string) -- anti-enumeration: a caller must never be
able to distinguish "no such tenant" from "that tenant exists but is
suspended" (US-11 review, Notes / Part A Risks).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Tenant

_UNKNOWN_OR_SUSPENDED_DETAIL = "not found"


async def resolve_public_tenant(
    tenant_slug: str,
    session: AsyncSession = Depends(get_session),
) -> Tenant:
    # --- Step 1: resolve tenant from the public slug -- tenants is
    # tenant-global, no RLS involved (ADR-001 §2).
    tenant = (
        await session.execute(select(Tenant).where(Tenant.public_slug == tenant_slug))
    ).scalar_one_or_none()
    if tenant is None or tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_UNKNOWN_OR_SUSPENDED_DETAIL
        )

    # --- Step 2: SET LOCAL before ANY tenant-scoped read/write (ADR-001 §1).
    # tenant.id came back from our own DB query (a validated UUID object,
    # never raw user input), so string-interpolating it here is safe --
    # PostgreSQL's SET command does not support bind parameters (same
    # justification as app.auth.dependencies.get_current_principal).
    await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant.id}'"))

    return tenant
