"""Entra ID (Azure AD) OIDC bearer token validation (US-10, ADR-001 §5).

Deliberately vendor-adjacent-but-abstracted: the JWKS-fetching / issuer
lookup step is behind the `JWKSProvider` protocol, so tests validate the
real signature/claims logic against a locally generated RSA keypair and a
`StaticJWKSProvider` — never a real Entra credential, and never a network
call to a real Entra endpoint (AGENTS.md: synthetic test data only; loop
policy: never proceed without a vendor credential).

This module has NO knowledge of Smart VMS's own `tenants`/`users` tables —
resolving the token's `tid` claim to a tenant row, checking tenant
suspension, and JIT-provisioning the user all happen one layer up, in
`app.auth.dependencies` (task 6), per the request-time sequence in ADR-001
§1 (as revised by the US-10 B1 remediation, docs/reviews/US-10-review.md).

US-10 B1 remediation: `EntraTokenValidator.validate()` NO LONGER reads the
`iss` claim from the token to decide what to trust — that was the root
cause of the B1 cross-tenant impersonation vulnerability (validating a
token's self-asserted issuer against itself). The caller now derives
`expected_issuer` from a trusted source (the DB-stored
`tenants.entra_tenant_id`) and passes it in; `peek_unverified_tenant_id()`
below exists ONLY to let the caller find that trusted tenant row in the
first place, from the still-unverified `tid` claim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import jwt
from jwt.algorithms import RSAAlgorithm


class TokenValidationError(Exception):
    """Any reason a bearer token is not acceptable. Callers map this to a
    401 response — never log the token or its claims (AGENTS.md: never log
    credentials/PII)."""


@dataclass(frozen=True)
class ValidatedTokenClaims:
    """Normalized, already-verified claims. `oid` is the canonical subject;
    `sub` is carried only as the documented fallback (ADR-001 §5) — callers
    must not mix the two without de-duplication. `name`/`preferred_username`
    are carried through (still integrity-protected by the same signature)
    so JIT provisioning has a real display name/email rather than a
    fabricated placeholder -- never logged anywhere (both are PII)."""

    tid: str
    oid: str | None
    sub: str
    aud: str
    name: str | None = None
    preferred_username: str | None = None


class JWKSProvider(Protocol):
    """Resolves a (issuer, kid) pair to a PEM-encoded public key usable to
    verify an RS256 signature."""

    def get_public_key(self, issuer: str, kid: str) -> str: ...


class StaticJWKSProvider:
    """A local/preloaded JWKS provider keyed by `kid` -> PEM public key. This
    is what tests use, loaded with a locally generated RSA keypair — never
    a real Entra key.

    Deliberately keyed by `kid` alone, NOT `(issuer, kid)`: in production,
    `HttpJWKSProvider` fetches keys from a per-tenant URL derived from a
    TRUSTED, DB-computed `issuer` (US-10 B1 remediation) — the security
    property that a genuine key can only be found at the genuine tenant's
    Microsoft-hosted endpoint is a property of that *real network fetch*,
    not something a same-process static test double can (or needs to)
    simulate. The `issuer` parameter this protocol method receives is
    accepted for interface compatibility but intentionally unused here;
    what actually proves issuer-pinning in tests is
    `EntraTokenValidator.validate()`'s own `issuer=expected_issuer` check
    against `jwt.decode`, which this test double does not and must not
    weaken."""

    def __init__(self, keys: dict[str, str]) -> None:
        self._keys = dict(keys)

    def get_public_key(self, issuer: str, kid: str) -> str:
        try:
            return self._keys[kid]
        except KeyError:
            raise TokenValidationError("unknown signing key for issuer/kid") from None


class HttpJWKSProvider:
    """Production implementation: per-issuer JWKS discovery over HTTPS, with
    an in-memory cache that refetches on a cache miss (handles key
    rotation — a `kid` absent from the cached set triggers one refetch
    before failing). NEVER invoked by any test in this repo; there is no
    real Entra ID access in this environment."""

    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self._cache: dict[str, dict[str, str]] = {}
        self._timeout_seconds = timeout_seconds

    def get_public_key(self, issuer: str, kid: str) -> str:
        keys = self._cache.get(issuer)
        if keys is None or kid not in keys:
            keys = self._fetch_jwks(issuer)
            self._cache[issuer] = keys
        try:
            return keys[kid]
        except KeyError:
            raise TokenValidationError("unknown signing key for issuer/kid") from None

    def _fetch_jwks(self, issuer: str) -> dict[str, str]:
        import httpx

        jwks_uri = f"{issuer.rstrip('/')}/discovery/v2.0/keys"
        response = httpx.get(jwks_uri, timeout=self._timeout_seconds)
        response.raise_for_status()
        jwks = response.json()
        return {
            jwk["kid"]: RSAAlgorithm.from_jwk(json.dumps(jwk)) for jwk in jwks.get("keys", [])
        }


def peek_unverified_tenant_id(token: str) -> str:
    """Reads the `tid` claim from the token WITHOUT verifying its signature.

    US-10 B1 remediation: this exists ONLY so a caller (app.auth.dependencies)
    can look up a CANDIDATE tenant row and derive that tenant's TRUSTED,
    DB-stored `entra_tenant_id` -- which is then used to compute the expected
    issuer/JWKS location for real validation. The value returned here must
    NEVER be used for any authorization decision on its own; it is discarded
    the moment `EntraTokenValidator.validate()` succeeds, whose returned,
    fully-VERIFIED `tid` is the only one downstream code may rely on. If the
    token is malformed, this raises the same `TokenValidationError` a full
    validation failure would, so callers can map it to a 401 uniformly."""
    try:
        unverified_claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise TokenValidationError("malformed token") from exc

    tid = unverified_claims.get("tid")
    if not tid:
        raise TokenValidationError("missing required token header/claims")
    return tid


class EntraTokenValidator:
    """Validates an Entra-issued bearer JWT: signature (via the injected
    `JWKSProvider`), `exp`/`nbf`, `aud` pinned to this API's configured App
    ID, and -- critically -- `iss` pinned to a caller-supplied
    `expected_issuer` (ADR-001 §5; US-10 B1 remediation).

    `expected_issuer` MUST be derived by the caller from a TRUSTED source
    (the DB-stored `tenants.entra_tenant_id`, resolved via the token's
    still-unverified `tid` claim) -- NEVER from the token's own `iss` claim.
    Reading `iss` from the token and validating the token's `iss` against
    itself is exactly the tautology that made B1 exploitable; this method no
    longer reads `iss` (or `tid`) from unverified claims for that purpose at
    all. JWKS keys are fetched using `expected_issuer` too, so a token
    cannot direct this validator to fetch signing keys from an
    attacker-controlled URL."""

    def __init__(self, jwks_provider: JWKSProvider, audience: str) -> None:
        self._jwks_provider = jwks_provider
        self._audience = audience

    def validate(self, token: str, expected_issuer: str) -> ValidatedTokenClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenValidationError("malformed token") from exc

        kid = header.get("kid")
        if not kid:
            raise TokenValidationError("missing required token header/claims")

        # Keys are fetched from the TRUSTED expected_issuer, never from the
        # token's own (attacker-controllable) `iss` claim.
        public_key = self._jwks_provider.get_public_key(expected_issuer, kid)

        try:
            claims = jwt.decode(
                token,
                key=public_key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=expected_issuer,
                options={"require": ["exp", "nbf", "iat", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenValidationError("token expired") from exc
        except jwt.ImmatureSignatureError as exc:
            raise TokenValidationError("token not yet valid (nbf)") from exc
        except jwt.InvalidAudienceError as exc:
            raise TokenValidationError("invalid audience") from exc
        except jwt.InvalidIssuerError as exc:
            raise TokenValidationError("invalid issuer") from exc
        except jwt.PyJWTError as exc:
            raise TokenValidationError("invalid token") from exc

        tid = claims.get("tid")
        oid = claims.get("oid")
        sub = claims.get("sub")
        if not tid:
            raise TokenValidationError("missing required token header/claims")
        if not oid and not sub:
            raise TokenValidationError("token has neither oid nor sub claim")

        return ValidatedTokenClaims(
            tid=tid,
            oid=oid,
            sub=sub,
            aud=claims["aud"],
            name=claims.get("name"),
            preferred_username=claims.get("preferred_username"),
        )
