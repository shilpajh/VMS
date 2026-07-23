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
`app.auth.dependencies` (task 6), per the exact 3-step request-time sequence
in ADR-001 §1.
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
    must not mix the two without de-duplication."""

    tid: str
    oid: str | None
    sub: str
    aud: str


class JWKSProvider(Protocol):
    """Resolves a (issuer, kid) pair to a PEM-encoded public key usable to
    verify an RS256 signature."""

    def get_public_key(self, issuer: str, kid: str) -> str: ...


class StaticJWKSProvider:
    """A local/preloaded JWKS provider keyed by (issuer, kid) -> PEM public
    key. This is what tests use, loaded with a locally generated RSA
    keypair — never a real Entra key."""

    def __init__(self, keys: dict[tuple[str, str], str]) -> None:
        self._keys = dict(keys)

    def get_public_key(self, issuer: str, kid: str) -> str:
        try:
            return self._keys[(issuer, kid)]
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


class EntraTokenValidator:
    """Validates an Entra-issued bearer JWT: signature (via the injected
    `JWKSProvider`), `exp`/`nbf`, and `aud` pinned to this API's configured
    App ID (ADR-001 §5). Does NOT check `tid` against a stored tenant --
    that's the caller's job (app.auth.dependencies, task 6)."""

    def __init__(self, jwks_provider: JWKSProvider, audience: str) -> None:
        self._jwks_provider = jwks_provider
        self._audience = audience

    def validate(self, token: str) -> ValidatedTokenClaims:
        try:
            header = jwt.get_unverified_header(token)
            unverified_claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as exc:
            raise TokenValidationError("malformed token") from exc

        kid = header.get("kid")
        issuer = unverified_claims.get("iss")
        tid = unverified_claims.get("tid")
        if not kid or not issuer or not tid:
            raise TokenValidationError("missing required token header/claims")

        public_key = self._jwks_provider.get_public_key(issuer, kid)

        try:
            claims = jwt.decode(
                token,
                key=public_key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=issuer,
                options={"require": ["exp", "nbf", "iat", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenValidationError("token expired") from exc
        except jwt.ImmatureSignatureError as exc:
            raise TokenValidationError("token not yet valid (nbf)") from exc
        except jwt.InvalidAudienceError as exc:
            raise TokenValidationError("invalid audience") from exc
        except jwt.PyJWTError as exc:
            raise TokenValidationError("invalid token") from exc

        oid = claims.get("oid")
        sub = claims.get("sub")
        if not oid and not sub:
            raise TokenValidationError("token has neither oid nor sub claim")

        return ValidatedTokenClaims(tid=tid, oid=oid, sub=sub, aud=claims["aud"])
