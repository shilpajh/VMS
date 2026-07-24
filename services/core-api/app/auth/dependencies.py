"""Tenant resolution + JIT provisioning (US-10, task 6).

Implements the request-time sequence from ADR-001 §1, as revised by the US-10
B1 security remediation (docs/reviews/US-10-review.md):
  0. Peek the token's STILL-UNVERIFIED `tid` claim -- used ONLY to look up a
     candidate tenant row, never trusted for authorization.
  1. Resolve tenant from that candidate `tid` via a lookup on the
     tenant-global `tenants` table -- no RLS involved.
  1b. Compute the EXPECTED issuer from the tenant's TRUSTED, DB-stored
     `entra_tenant_id` (never from the token's own `iss` claim), then run
     full signature+issuer+audience validation against it. Only after this
     succeeds is the token's (now-verified) `tid` trusted.
  2. `SET LOCAL app.current_tenant_id` inside the request transaction.
  3. Only then read/JIT-insert into `users` -- the JIT insert satisfies the
     RLS `WITH CHECK` clause because the GUC is already set at that point.

Disabled-user and tenant-suspension status are re-checked against current
DB state on every call (never cached/trusted from token-mint time) --
ADR-001's stateless-revocation requirement (task 10 exercises this
end-to-end).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.entra import (
    EntraTokenValidator,
    HttpJWKSProvider,
    TokenValidationError,
    peek_unverified_tenant_id,
)
from app.config import settings
from app.db.session import get_session
from app.domain.audit import write_audit_event
from app.domain.rbac import get_user_permissions
from app.models import Tenant, User

_bearer_scheme = HTTPBearer(auto_error=False)

JIT_PROVISION_REASON = "first_login_self_provisioning"


@dataclass(frozen=True)
class Principal:
    """Normalized, tenant-bound authenticated principal attached to the
    request. Never carries raw token claims or `external_idp_subject`
    beyond what's needed internally -- API DTOs (task 8) must not
    re-serialize it verbatim."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    external_idp_subject: str
    permissions: frozenset[str]


def get_token_validator() -> EntraTokenValidator:
    """Production wiring: real per-issuer JWKS discovery over HTTPS. Tests
    override this via FastAPI's dependency_overrides (or call
    get_current_principal directly with their own validator) -- never
    exercised against a real Entra endpoint in this repo."""
    return EntraTokenValidator(
        jwks_provider=HttpJWKSProvider(), audience=settings.entra_api_audience
    )


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
    validator: EntraTokenValidator = Depends(get_token_validator),
) -> Principal:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token"
        )

    # --- Step 0 (US-10 B1 remediation): peek the STILL-UNVERIFIED `tid` claim
    # ONLY to look up a candidate tenant row. This value is never trusted for
    # authorization -- it is used solely to derive the TRUSTED, DB-stored
    # `entra_tenant_id` needed to compute the expected issuer/JWKS location
    # for the real validation that follows. Reading the token's own `iss`
    # claim and validating it against itself (the pre-fix behavior) is
    # exactly the tautology that made cross-tenant token forgery possible.
    try:
        candidate_tid = peek_unverified_tenant_id(credentials.credentials)
    except TokenValidationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        ) from None

    # --- Step 1: resolve tenant from the (still-unverified) `tid` -- tenants
    # is tenant-global, no RLS. This lookup is safe pre-validation because it
    # is not itself an authorization decision: it exists only to obtain the
    # tenant's TRUSTED `entra_tenant_id` for computing the expected issuer.
    tenant = (
        await session.execute(select(Tenant).where(Tenant.entra_tenant_id == candidate_tid))
    ).scalar_one_or_none()
    if tenant is None or tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown or suspended tenant"
        )

    # --- Step 1b: compute the EXPECTED issuer from the trusted, DB-stored
    # entra_tenant_id (never from the token's own `iss` claim), then run full
    # signature+issuer+audience validation against it. Only a token whose
    # real `iss` exactly matches this trusted authority for THIS tenant can
    # pass; JWKS keys are fetched from this same trusted location.
    expected_issuer = f"https://login.microsoftonline.com/{tenant.entra_tenant_id}/v2.0"
    try:
        claims = validator.validate(credentials.credentials, expected_issuer=expected_issuer)
    except TokenValidationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        ) from None

    # Defense-in-depth: the now-VERIFIED `tid` must match the tenant the
    # expected issuer was computed from. This should always hold given issuer
    # pinning above, but fail closed on any anomaly rather than assume it.
    if claims.tid != tenant.entra_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        ) from None

    # --- Step 2: SET LOCAL before ANY scoped read/write (ADR-001 §1).
    # tenant.id came back from our own DB query (a validated UUID object,
    # never raw user input) so string-interpolating it here is safe --
    # PostgreSQL's SET command does not support bind parameters.
    await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant.id}'"))

    external_idp_subject = claims.oid or claims.sub

    # --- Step 3: only now read/JIT-provision the user.
    user = (
        await session.execute(
            select(User).where(
                User.tenant_id == tenant.id,
                User.external_idp_subject == external_idp_subject,
            )
        )
    ).scalar_one_or_none()

    is_new_user = user is None
    if user is None:
        display_name = claims.name or external_idp_subject
        email = claims.preferred_username or claims.name or f"{external_idp_subject}@unknown.invalid"
        user = User(
            tenant_id=tenant.id,
            external_idp_subject=external_idp_subject,
            email=email,
            display_name=display_name,
        )
        session.add(user)
        await session.flush()  # WITH CHECK is satisfied: GUC already set above.

        await write_audit_event(
            session,
            tenant_id=tenant.id,
            event_type="user.provisioned",
            actor=external_idp_subject,  # self-provision: actor is the user themself
            target_type="user",
            target_id=user.id,
            reason=JIT_PROVISION_REASON,
            correlation_id=uuid.uuid4(),
        )

    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user disabled")

    permissions = await get_user_permissions(session, tenant.id, user.id)

    # Deliberately no commit here: SET LOCAL is transaction-scoped, and the
    # rest of THIS request may still need to run tenant-scoped queries under
    # the same GUC. The request's single transaction is committed once, at
    # the end, by app.db.session.get_session.
    return Principal(
        tenant_id=tenant.id,
        user_id=user.id,
        external_idp_subject=external_idp_subject,
        permissions=frozenset(permissions),
    )
