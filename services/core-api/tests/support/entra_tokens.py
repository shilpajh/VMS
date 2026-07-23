"""Test-only synthetic Entra ID token issuance.

Generates a local RSA keypair and signs RS256 JWTs shaped like real Entra ID
access tokens (iss/tid/aud/oid/sub/exp/nbf). Never a real Entra credential;
never makes a network call. Used to exercise app.auth.entra's real
signature/claims verification logic end-to-end (AGENTS.md: synthetic test
data only).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

DEFAULT_TEST_ISSUER = "https://login.microsoftonline.com/test-issuer-not-real/v2.0"


@dataclass
class SyntheticIdp:
    issuer: str
    kid: str
    private_key_pem: str
    public_key_pem: str

    def issue_token(
        self,
        *,
        tid: str,
        aud: str,
        oid: str | None = "synthetic-oid",
        sub: str = "synthetic-sub",
        expires_in_seconds: int = 3600,
        not_before_offset_seconds: int = 0,
        extra_claims: dict | None = None,
    ) -> str:
        now = int(time.time())
        claims: dict = {
            "iss": self.issuer,
            "tid": tid,
            "aud": aud,
            "iat": now,
            "nbf": now + not_before_offset_seconds,
            "exp": now + expires_in_seconds,
            "sub": sub,
        }
        if oid is not None:
            claims["oid"] = oid
        if extra_claims:
            claims.update(extra_claims)
        return jwt.encode(
            claims, self.private_key_pem, algorithm="RS256", headers={"kid": self.kid}
        )


def make_synthetic_idp(issuer: str = DEFAULT_TEST_ISSUER) -> SyntheticIdp:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    kid = f"kid-{uuid.uuid4().hex[:8]}"
    return SyntheticIdp(issuer=issuer, kid=kid, private_key_pem=private_pem, public_key_pem=public_pem)
