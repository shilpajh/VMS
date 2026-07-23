"""Application-level envelope encryption for `outbox_messages.payload`
(US-11, task 5, ADR-002 §5).

The payload carries a live credential (the plaintext check-in code) plus
visitor PII -- RLS + disk encryption is not sufficient (ADR-002 §5). Every
encryption generates a fresh random per-message data key (DEK), encrypts the
plaintext with it (AES-256-GCM), then "wraps" (encrypts) the DEK itself
under a master/Key-Vault key. The wrapped DEK, its nonce, and the ciphertext
are packed into one opaque blob stored in `outbox_messages.payload`;
`payload_key_ref` records which master key/version wrapped the DEK, so a
future key rotation can be resolved without re-encrypting historical rows
(ADR-002 §5/O3: "the exact primitive... is an execution/security-review
detail to confirm" -- AES-GCM envelope is the concrete choice made here).

Deliberately vendor-adjacent-but-abstracted, same discipline as
app.auth.entra's JWKSProvider: the master-key wrap/unwrap operation is
behind the `EnvelopeKeyProvider` protocol. `LocalEnvelopeKeyProvider` (a
locally generated AES key) is what every test in this repo uses --
`KeyVaultEnvelopeKeyProvider` is production wiring, NEVER exercised by any
test here, because there is no real Azure Key Vault access in this
environment (AGENTS.md: never proceed without a vendor credential).
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

_DEK_SIZE_BYTES = 32  # AES-256
_NONCE_SIZE_BYTES = 12  # standard AES-GCM nonce size


class EnvelopeKeyProvider(Protocol):
    """Wraps/unwraps a per-message data-encryption key (DEK) under a
    master key. `key_ref` identifies which master key/version this
    provider currently wraps with (recorded on the outbox row for
    rotation)."""

    key_ref: str

    def wrap_key(self, data_key: bytes) -> bytes: ...
    def unwrap_key(self, wrapped_key: bytes, key_ref: str) -> bytes: ...


class LocalEnvelopeKeyProvider:
    """Dev/test-only master key held in process memory (AES-256-GCM wrap).
    NEVER used in production -- production wiring is
    KeyVaultEnvelopeKeyProvider (app.config.settings decides which is
    constructed, mirroring get_token_validator's production/test split)."""

    def __init__(self, master_key: bytes | None = None, key_ref: str = "local-dev-test-key-v1") -> None:
        self._master_key = master_key or AESGCM.generate_key(bit_length=256)
        self.key_ref = key_ref

    def wrap_key(self, data_key: bytes) -> bytes:
        nonce = os.urandom(_NONCE_SIZE_BYTES)
        wrapped = AESGCM(self._master_key).encrypt(nonce, data_key, None)
        return nonce + wrapped

    def unwrap_key(self, wrapped_key: bytes, key_ref: str) -> bytes:
        nonce, wrapped = wrapped_key[:_NONCE_SIZE_BYTES], wrapped_key[_NONCE_SIZE_BYTES:]
        return AESGCM(self._master_key).decrypt(nonce, wrapped, None)


class KeyVaultEnvelopeKeyProvider:
    """Production implementation: wraps/unwraps the per-message DEK using an
    Azure Key Vault key's wrapKey/unwrapKey operations. NEVER invoked by any
    test in this repo -- there is no real Key Vault access in this
    environment (mirrors app.auth.entra.HttpJWKSProvider's discipline: the
    Azure SDK is imported lazily, inside the method, so its absence never
    breaks tests/dev that never call this class)."""

    def __init__(self, key_vault_key_id: str) -> None:
        self.key_ref = key_vault_key_id

    def wrap_key(self, data_key: bytes) -> bytes:
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415
        from azure.keyvault.keys.crypto import (  # noqa: PLC0415
            CryptographyClient,
            KeyWrapAlgorithm,
        )

        client = CryptographyClient(self.key_ref, DefaultAzureCredential())
        result = client.wrap_key(KeyWrapAlgorithm.aes_256, data_key)
        return result.encrypted_key

    def unwrap_key(self, wrapped_key: bytes, key_ref: str) -> bytes:
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415
        from azure.keyvault.keys.crypto import (  # noqa: PLC0415
            CryptographyClient,
            KeyWrapAlgorithm,
        )

        client = CryptographyClient(key_ref, DefaultAzureCredential())
        result = client.unwrap_key(KeyWrapAlgorithm.aes_256, wrapped_key)
        return result.key


@dataclass(frozen=True)
class EncryptedPayload:
    """What gets stored on `outbox_messages`: `ciphertext` -> `payload`
    (BYTEA), `key_ref` -> `payload_key_ref`."""

    ciphertext: bytes
    key_ref: str


def _pack(wrapped_key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    # length-prefixed blob: [4-byte wrapped_key len][wrapped_key][nonce][ciphertext]
    return struct.pack(">I", len(wrapped_key)) + wrapped_key + nonce + ciphertext


def _unpack(blob: bytes) -> tuple[bytes, bytes, bytes]:
    (wrapped_key_len,) = struct.unpack(">I", blob[:4])
    offset = 4
    wrapped_key = blob[offset : offset + wrapped_key_len]
    offset += wrapped_key_len
    nonce = blob[offset : offset + _NONCE_SIZE_BYTES]
    offset += _NONCE_SIZE_BYTES
    ciphertext = blob[offset:]
    return wrapped_key, nonce, ciphertext


def encrypt_payload(plaintext: bytes, provider: EnvelopeKeyProvider) -> EncryptedPayload:
    """Generates a fresh random DEK + nonce for THIS message, encrypts
    `plaintext` with it, wraps the DEK under the provider's master key, and
    packs everything into one opaque blob. Never deterministic -- two
    encryptions of identical plaintext never produce identical ciphertext."""
    data_key = AESGCM.generate_key(bit_length=_DEK_SIZE_BYTES * 8)
    nonce = os.urandom(_NONCE_SIZE_BYTES)
    ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, None)
    wrapped_key = provider.wrap_key(data_key)
    return EncryptedPayload(ciphertext=_pack(wrapped_key, nonce, ciphertext), key_ref=provider.key_ref)


def decrypt_payload(ciphertext: bytes, key_ref: str, provider: EnvelopeKeyProvider) -> bytes:
    """Decrypted only transiently, in the (not-yet-built) relay worker's
    memory -- never logged, never persisted in cleartext (ADR-002 §5)."""
    wrapped_key, nonce, aes_ciphertext = _unpack(ciphertext)
    data_key = provider.unwrap_key(wrapped_key, key_ref)
    return AESGCM(data_key).decrypt(nonce, aes_ciphertext, None)


def get_envelope_key_provider() -> EnvelopeKeyProvider:
    """Production wiring, used as a FastAPI dependency default (mirrors
    app.auth.dependencies.get_token_validator). Tests override this via
    FastAPI's dependency_overrides with a LocalEnvelopeKeyProvider -- never
    exercised against a real Key Vault in this repo."""
    return KeyVaultEnvelopeKeyProvider(key_vault_key_id=settings.envelope_encryption_key_ref)
