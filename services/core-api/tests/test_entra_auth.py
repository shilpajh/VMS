"""Task 5 (US-10): Entra ID bearer token validation (app/auth/entra.py).

All tokens here are signed with a locally generated RSA keypair
(tests/support/entra_tokens.py) via a StaticJWKSProvider -- never a real
Entra credential, never a network call to a real Entra endpoint.

`tid`-vs-stored-tenant and unknown/suspended-tenant rejection are DB-backed
concerns resolved one layer up (app.auth.dependencies, task 6) and are
tested end-to-end as 401s there (tests/test_jit_provisioning.py /
tests/test_stateless_revocation.py). This file covers the pure
signature/claims logic that module owns on its own -- including, per the
US-10 B1 remediation (docs/reviews/US-10-review.md), that `validate()` no
longer trusts the token's own `iss` claim: callers must supply a trusted
`expected_issuer`, and a token is rejected if its real `iss` doesn't match
it exactly, regardless of who signed it.
"""

from __future__ import annotations

import pytest

from app.auth.entra import EntraTokenValidator, StaticJWKSProvider, TokenValidationError
from tests.support.entra_tokens import entra_issuer_for, make_synthetic_idp

AUDIENCE = "api://smart-vms-core-api-dev-placeholder"
TENANT_ID = "acme-entra-tid"
EXPECTED_ISSUER = entra_issuer_for(TENANT_ID)


@pytest.fixture()
def idp():
    return make_synthetic_idp()


@pytest.fixture()
def validator(idp):
    provider = StaticJWKSProvider({idp.kid: idp.public_key_pem})
    return EntraTokenValidator(jwks_provider=provider, audience=AUDIENCE)


def test_valid_token_is_accepted(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud=AUDIENCE, oid="new-oid")
    claims = validator.validate(token, expected_issuer=EXPECTED_ISSUER)
    assert claims.tid == TENANT_ID
    assert claims.oid == "new-oid"
    assert claims.aud == AUDIENCE


def test_wrong_audience_is_rejected(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud="api://some-other-app")
    with pytest.raises(TokenValidationError):
        validator.validate(token, expected_issuer=EXPECTED_ISSUER)


def test_expired_token_is_rejected(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud=AUDIENCE, expires_in_seconds=-10)
    with pytest.raises(TokenValidationError):
        validator.validate(token, expected_issuer=EXPECTED_ISSUER)


def test_not_yet_valid_token_is_rejected(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud=AUDIENCE, not_before_offset_seconds=3600)
    with pytest.raises(TokenValidationError):
        validator.validate(token, expected_issuer=EXPECTED_ISSUER)


def test_signature_from_unknown_key_is_rejected(validator) -> None:
    other_idp = make_synthetic_idp()  # different keypair, not in the validator's JWKS
    token = other_idp.issue_token(tid=TENANT_ID, aud=AUDIENCE)
    with pytest.raises(TokenValidationError):
        validator.validate(token, expected_issuer=EXPECTED_ISSUER)


def test_oid_is_canonical_subject_when_present(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud=AUDIENCE, oid="the-oid", sub="the-sub")
    claims = validator.validate(token, expected_issuer=EXPECTED_ISSUER)
    assert claims.oid == "the-oid"
    assert claims.sub == "the-sub"


def test_sub_is_used_when_oid_absent(idp, validator) -> None:
    token = idp.issue_token(tid=TENANT_ID, aud=AUDIENCE, oid=None, sub="fallback-sub")
    claims = validator.validate(token, expected_issuer=EXPECTED_ISSUER)
    assert claims.oid is None
    assert claims.sub == "fallback-sub"


def test_malformed_token_is_rejected(validator) -> None:
    with pytest.raises(TokenValidationError):
        validator.validate("not-a-jwt", expected_issuer=EXPECTED_ISSUER)


# --- US-10 B1 remediation: issuer-pinning-specific tests -------------------


def test_forged_issuer_from_a_key_the_validator_trusts_is_rejected(idp, validator) -> None:
    """Even when the SAME key/kid the validator already trusts signs the
    token (i.e. not an 'unknown key' rejection), a token whose `iss` doesn't
    equal the caller-supplied `expected_issuer` must still be rejected. This
    is the exact gap the pre-fix suite never covered (B1's suggested
    remediation note): 'a validly-signed token from an unexpected/attacker
    issuer'."""
    token = idp.issue_token(
        tid=TENANT_ID, aud=AUDIENCE, iss="https://attacker.example/forged-issuer"
    )
    with pytest.raises(TokenValidationError):
        validator.validate(token, expected_issuer=EXPECTED_ISSUER)


def test_well_formed_issuer_for_a_different_tenant_is_rejected(idp, validator) -> None:
    """A validly-signed, real-looking Microsoft-authority issuer string is
    still rejected if it names a DIFFERENT tenant than the one
    `expected_issuer` was computed for."""
    other_tenant_issuer = entra_issuer_for("some-other-tenant-tid")
    token = idp.issue_token(tid=TENANT_ID, aud=AUDIENCE, iss=other_tenant_issuer)
    with pytest.raises(TokenValidationError):
        validator.validate(token, expected_issuer=EXPECTED_ISSUER)
