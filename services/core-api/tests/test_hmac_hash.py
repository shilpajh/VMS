"""Task 3 (US-13a): keyed HMAC-SHA256 helper (app/crypto/hmac_hash.py).

Why HMAC and not bare SHA-256 (US-13 review Should-fix #3): a 6-digit OTP
has only 10^6 preimages; a bare SHA-256 of it is instantly reversible if
the hash leaks. Keying the hash under a secret an attacker doesn't have
makes a leaked hash useless without the key.
"""

from __future__ import annotations

from app.crypto.hmac_hash import LocalHmacKeyProvider, hmac_hash, verify_hmac


def test_hmac_is_deterministic_under_a_fixed_key() -> None:
    provider = LocalHmacKeyProvider(key=b"fixed-test-key")
    assert hmac_hash("123456", provider) == hmac_hash("123456", provider)


def test_hmac_differs_across_keys() -> None:
    a = LocalHmacKeyProvider(key=b"key-a")
    b = LocalHmacKeyProvider(key=b"key-b")
    assert hmac_hash("123456", a) != hmac_hash("123456", b)


def test_hmac_differs_across_inputs() -> None:
    provider = LocalHmacKeyProvider(key=b"fixed-test-key")
    assert hmac_hash("123456", provider) != hmac_hash("123457", provider)


def test_hmac_output_is_not_the_plaintext() -> None:
    provider = LocalHmacKeyProvider(key=b"fixed-test-key")
    digest = hmac_hash("123456", provider)
    assert "123456" not in digest
    assert len(digest) == 64  # sha256 hex


def test_verify_hmac_constant_time_true_on_match_false_on_mismatch() -> None:
    provider = LocalHmacKeyProvider(key=b"fixed-test-key")
    digest = hmac_hash("123456", provider)
    assert verify_hmac("123456", digest, provider) is True
    assert verify_hmac("000000", digest, provider) is False


def test_local_provider_key_never_appears_in_repr() -> None:
    provider = LocalHmacKeyProvider(key=b"super-secret-key-material")
    assert "super-secret-key-material" not in repr(provider)
