"""US-10 B1 remediation: Entra token `iss` (issuer) pinning.

Proves and closes the cross-tenant impersonation vulnerability found in
`/verify-story`'s security review (docs/reviews/US-10-review.md, BLOCKING
B1): the validator used to read the token's own (attacker-controlled) `iss`
claim, fetch JWKS from that same self-asserted URL, and check `iss == iss`
-- a tautology. An attacker who hosts their own JWKS at any URL, signs a
token with `tid`/`oid` set to a real victim tenant/admin, and sets `iss` to
their own URL was fully authenticated as that victim.

The fix: the EXPECTED issuer is derived from the DB-stored, trusted
`tenants.entra_tenant_id` (looked up via the token's still-unverified `tid`
claim, used ONLY to find a candidate tenant row -- never itself trusted for
authorization) BEFORE full signature+issuer+audience validation runs. Full
validation happens against that trusted expected issuer, so a token whose
real `iss` doesn't equal it is rejected regardless of who signed it or
which key was used.

All tokens here are signed with locally generated RSA keypairs
(tests/support/entra_tokens.py) -- never a real Entra credential, never a
real network call (AGENTS.md: synthetic test data only).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.dependencies import get_current_principal
from app.auth.entra import EntraTokenValidator, StaticJWKSProvider
from tests.conftest import assign_role, insert_tenant, insert_user
from tests.support.entra_tokens import entra_issuer_for, make_synthetic_idp

AUDIENCE = "api://smart-vms-core-api-dev-placeholder"


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def test_forged_issuer_cross_tenant_impersonation_is_rejected(app_session) -> None:
    """The exact B1 exploit: attacker hosts their own JWKS at a URL of their
    choosing, signs a token with their own key, sets `iss` to that URL, and
    sets `tid`/`oid` to a REAL victim tenant's `entra_tenant_id` and a real
    victim admin's `oid`. Before the fix this authenticated the attacker as
    the victim admin; after the fix it must be rejected with 401 because the
    attacker's `iss` does not equal the trusted, DB-derived expected issuer
    for the victim tenant."""
    victim_entra_tid = f"victim-entra-tid-{uuid.uuid4().hex[:8]}"
    victim_tenant_id = insert_tenant("Victim Co", victim_entra_tid)
    victim_admin_oid = f"victim-admin-oid-{uuid.uuid4().hex[:8]}"
    victim_admin_user_id = insert_user(victim_tenant_id, victim_admin_oid)
    assign_role(victim_tenant_id, victim_admin_user_id, "tenant_admin")

    # Attacker generates their OWN keypair and hosts a JWKS at a URL they
    # control -- simulated here (no real network call) by a StaticJWKSProvider
    # standing in for exactly what an HttpJWKSProvider would have fetched had
    # it followed the token's own self-asserted `iss`.
    attacker_idp = make_synthetic_idp()
    forged_issuer = "https://attacker.example/not-a-real-microsoft-authority"
    forged_token = attacker_idp.issue_token(
        tid=victim_entra_tid,  # attacker sets tid to the REAL victim tenant
        aud=AUDIENCE,
        oid=victim_admin_oid,  # ...and impersonates a known victim admin
        iss=forged_issuer,  # attacker's own issuer -- not a real Microsoft authority
    )
    attacker_provider = StaticJWKSProvider({attacker_idp.kid: attacker_idp.public_key_pem})
    attacker_controlled_validator = EntraTokenValidator(
        jwks_provider=attacker_provider, audience=AUDIENCE
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(
            credentials=_bearer(forged_token),
            session=app_session,
            validator=attacker_controlled_validator,
        )
    assert exc_info.value.status_code == 401


async def test_well_formed_but_wrong_tenant_issuer_is_rejected(app_session) -> None:
    """Even a validly-signed token whose `iss` is a well-formed Microsoft
    identity platform authority string is rejected if it names a DIFFERENT
    tenant than the one the token's `tid` resolves to -- issuer must be
    pinned to the SAME tenant, not merely 'Microsoft-shaped'."""
    idp = make_synthetic_idp()
    other_entra_tid = f"other-entra-tid-{uuid.uuid4().hex[:8]}"
    insert_tenant("Other Co", other_entra_tid)
    target_entra_tid = f"target-entra-tid-{uuid.uuid4().hex[:8]}"
    insert_tenant("Target Co", target_entra_tid)

    # tid claims to be "Target Co" but iss is a real-looking Microsoft
    # authority string for "Other Co" -- a mismatch that must be rejected.
    token = idp.issue_token(
        tid=target_entra_tid,
        aud=AUDIENCE,
        iss=entra_issuer_for(other_entra_tid),
    )
    provider = StaticJWKSProvider({idp.kid: idp.public_key_pem})
    validator = EntraTokenValidator(jwks_provider=provider, audience=AUDIENCE)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(
            credentials=_bearer(token), session=app_session, validator=validator
        )
    assert exc_info.value.status_code == 401


async def test_legitimate_token_with_correctly_pinned_issuer_is_accepted(app_session) -> None:
    """Sanity/control: a token whose `iss` genuinely matches the resolved
    tenant's expected Microsoft authority is still accepted -- the fix must
    not break the happy path."""
    idp = make_synthetic_idp()
    entra_tid = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tid)
    oid = f"oid-{uuid.uuid4().hex[:8]}"
    token = idp.issue_token(tid=entra_tid, aud=AUDIENCE, oid=oid)
    provider = StaticJWKSProvider({idp.kid: idp.public_key_pem})
    validator = EntraTokenValidator(jwks_provider=provider, audience=AUDIENCE)

    principal = await get_current_principal(
        credentials=_bearer(token), session=app_session, validator=validator
    )
    assert principal.tenant_id == tenant_id
    assert principal.external_idp_subject == oid
