"""Keyed HMAC-SHA256 hashing for low-entropy portal credentials (US-13a,
ADR-004): the 6-digit OTP and the verification token.

A bare SHA-256 is safe only for a high-entropy secret (the check-in code is
`secrets.token_urlsafe(24)` ~192 bits -- US-01 could bare-hash it). A
6-digit OTP has only 10^6 preimages: a bare hash is instantly reversible if
it leaks. Keying the hash under a Key-Vault-managed secret an attacker does
not have makes a leaked hash useless without the key (US-13 review
Should-fix #3).

Same Local/KeyVault provider split as app.crypto.envelope:
`LocalHmacKeyProvider` (in-process key) is what every test uses;
`KeyVaultHmacKeyProvider` is production wiring, NEVER exercised here (no real
Key Vault in this environment). The key material is never logged or exposed
via repr/str.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Protocol

from app.config import settings


class HmacKeyProvider(Protocol):
    def key(self) -> bytes: ...


class LocalHmacKeyProvider:
    """Dev/test-only HMAC key held in process memory. NEVER used in
    production -- production wiring is KeyVaultHmacKeyProvider."""

    def __init__(self, key: bytes) -> None:
        self._key = key

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(key=<redacted>)"

    def key(self) -> bytes:
        return self._key


class KeyVaultHmacKeyProvider:
    """Production implementation: fetches the HMAC secret from Azure Key
    Vault. NEVER invoked by any test in this repo (no real Key Vault
    access). Azure SDK imported lazily so its absence never breaks
    tests/dev (mirrors app.crypto.envelope.KeyVaultEnvelopeKeyProvider and
    app.auth.entra.HttpJWKSProvider)."""

    def __init__(self, secret_id: str) -> None:
        self._secret_id = secret_id

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(secret_id=<redacted>)"

    def key(self) -> bytes:
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415
        from azure.keyvault.secrets import SecretClient  # noqa: PLC0415

        vault_url, _, name = self._secret_id.rpartition("/")
        client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
        return client.get_secret(name).value.encode()


def hmac_hash(plaintext: str, provider: HmacKeyProvider) -> str:
    """HMAC-SHA256 of `plaintext` under the provider's key, hex digest."""
    return hmac.new(provider.key(), plaintext.encode(), hashlib.sha256).hexdigest()


def verify_hmac(plaintext: str, expected_digest: str, provider: HmacKeyProvider) -> bool:
    """Constant-time comparison of `hmac_hash(plaintext)` against
    `expected_digest` -- `hmac.compare_digest` avoids a timing side channel
    on the comparison itself."""
    return hmac.compare_digest(hmac_hash(plaintext, provider), expected_digest)


def get_hmac_key_provider() -> HmacKeyProvider:
    """Production wiring, used as a FastAPI dependency default (mirrors
    app.crypto.envelope.get_envelope_key_provider). Tests override this with
    a LocalHmacKeyProvider -- never exercised against a real Key Vault."""
    return KeyVaultHmacKeyProvider(secret_id=settings.otp_hmac_key_ref)
