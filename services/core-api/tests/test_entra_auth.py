"""Task 5 (US-10): Entra ID bearer token validation (app/auth/entra.py).

All tokens here are signed with a locally generated RSA keypair
(tests/support/entra_tokens.py) via a StaticJWKSProvider -- never a real
Entra credential, never a network call to a real Entra endpoint.

`tid`-vs-stored-tenant and unknown/suspended-tenant rejection are DB-backed
concerns resolved one layer up (app.auth.dependencies, task 6) and are
tested end-to-end as 401s there (tests/test_jit_provisioning.py /
tests/test_stateless_revocation.py). This file covers the pure
signature/claims logic that module owns on its own.
"""

from __future__ import annotations

import pytest

from app.auth.entra import EntraTokenValidator, StaticJWKSProvider, TokenValidationError
from tests.support.entra_tokens import make_synthetic_idp

AUDIENCE = "api://smart-vms-core-api-dev-placeholder"
TENANT_ID = "acme-entra-tid"


@pytest.fixture()
def idp():
    return make_synthetic_idp()


@pytest.fixture()
def validator(idp):
    provider = StaticJWKSProvider({(idp.issuer, idp.kid): idp.public_key_pem})
    return EntraTokenValidator(jwks_provider=provider, audience=AUDIENCE)


def test_valid_token_is_accepted(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud=AUDIENCE, oid="new-oid")
    claims = validator.validate(token)
    assert claims.tid == TENANT_ID
    assert claims.oid == "new-oid"
    assert claims.aud == AUDIENCE


def test_wrong_audience_is_rejected(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud="api://some-other-app")
    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_expired_token_is_rejected(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud=AUDIENCE, expires_in_seconds=-10)
    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_not_yet_valid_token_is_rejected(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud=AUDIENCE, not_before_offset_seconds=3600)
    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_signature_from_unknown_key_is_rejected(validator) -> None:
    other_idp = make_synthetic_idp()  # different keypair, not in the validator's JWKS
    token = other_idp.issue_token(tid=TENANT_ID, aud=AUDIENCE)
    with pytest.raises(TokenValidationError):
        validator.validate(token)


def test_oid_is_canonical_subject_when_present(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud=AUDIENCE, oid="the-oid", sub="the-sub")
    claims = validator.validate(token)
    assert claims.oid == "the-oid"
    assert claims.sub == "the-sub"


def test_sub_is_used_when_oid_absent(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud=AUDIENCE, oid=None, sub="fallback-sub")
    claims = validator.validate(token)
    assert claims.oid is None
    assert claims.sub == "fallback-sub"


def test_malformed_token_is_rejected(validator) -> None:
    with pytest.raises(TokenValidationError):
        validator.validate("not-a-jwt")
