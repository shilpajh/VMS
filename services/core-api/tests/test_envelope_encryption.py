"""Task 5 (US-11): envelope encryption helper (app/crypto/envelope.py),
ADR-002 §5. Round-trip encrypt/decrypt against a LOCAL test key only --
never a real Azure Key Vault call in this environment (no real Key Vault
account exists here; same injectable-interface discipline as
app/auth/entra.py's JWKSProvider).
"""

from __future__ import annotations

import pytest

from app.crypto.envelope import LocalEnvelopeKeyProvider, decrypt_payload, encrypt_payload


def test_round_trip_encrypt_decrypt_recovers_plaintext() -> None:
    provider = LocalEnvelopeKeyProvider()
    plaintext = b'{"checkin_code": "super-secret-token", "contact_value": "a@example.com"}'

    encrypted = encrypt_payload(plaintext, provider)
    recovered = decrypt_payload(encrypted.ciphertext, encrypted.key_ref, provider)

    assert recovered == plaintext


def test_ciphertext_is_not_the_plaintext() -> None:
    provider = LocalEnvelopeKeyProvider()
    plaintext = b"the plaintext check-in code and PII"

    encrypted = encrypt_payload(plaintext, provider)

    assert encrypted.ciphertext != plaintext
    assert plaintext not in encrypted.ciphertext


def test_key_ref_is_recorded_for_rotation() -> None:
    provider = LocalEnvelopeKeyProvider(key_ref="local-dev-test-key-v7")
    encrypted = encrypt_payload(b"payload", provider)
    assert encrypted.key_ref == "local-dev-test-key-v7"


def test_two_encryptions_of_the_same_plaintext_produce_different_ciphertext() -> None:
    """Each encryption uses a fresh random data key + nonce -- ciphertext
    must never be deterministic (would leak equality of two payloads)."""
    provider = LocalEnvelopeKeyProvider()
    plaintext = b"same plaintext both times"

    first = encrypt_payload(plaintext, provider)
    second = encrypt_payload(plaintext, provider)

    assert first.ciphertext != second.ciphertext


def test_decrypt_fails_with_wrong_master_key() -> None:
    provider_a = LocalEnvelopeKeyProvider()
    provider_b = LocalEnvelopeKeyProvider()  # different random master key

    encrypted = encrypt_payload(b"secret", provider_a)

    with pytest.raises(Exception):
        decrypt_payload(encrypted.ciphertext, encrypted.key_ref, provider_b)


def test_decrypt_fails_if_ciphertext_is_tampered() -> None:
    provider = LocalEnvelopeKeyProvider()
    encrypted = encrypt_payload(b"secret payload", provider)

    tampered = bytearray(encrypted.ciphertext)
    tampered[-1] ^= 0xFF

    with pytest.raises(Exception):
        decrypt_payload(bytes(tampered), encrypted.key_ref, provider)
