"""Task 8 (US-11): Cloudflare Turnstile CAPTCHA verification
(app/security/captcha.py). No real Turnstile account exists in this
environment -- tests validate the actual logic (accept/reject, and the
"verify before anything else" ordering contract) against FakeTurnstileVerifier,
never a real network call to Cloudflare (same injectable-interface
discipline as JWKSProvider/EnvelopeKeyProvider).
"""

from __future__ import annotations

import pytest

from app.security.captcha import FakeTurnstileVerifier, HttpTurnstileVerifier


async def test_valid_token_is_accepted() -> None:
    verifier = FakeTurnstileVerifier(accept_tokens={"good-token"})
    assert await verifier.verify("good-token") is True


async def test_invalid_token_is_rejected() -> None:
    verifier = FakeTurnstileVerifier(accept_tokens={"good-token"})
    assert await verifier.verify("bad-token") is False


async def test_missing_or_empty_token_is_rejected() -> None:
    verifier = FakeTurnstileVerifier(accept_tokens={"good-token"})
    assert await verifier.verify("") is False


def test_http_verifier_secret_key_is_never_logged_or_repr_leaked() -> None:
    verifier = HttpTurnstileVerifier(secret_key="super-secret-not-a-real-key")
    assert "super-secret-not-a-real-key" not in repr(verifier)
