"""Cloudflare Turnstile CAPTCHA verification (US-11, task 8).

No real Cloudflare Turnstile account exists in this environment.
`TurnstileVerifier` is an injectable interface, same discipline as
app.auth.entra's JWKSProvider: `HttpTurnstileVerifier` is the real
`siteverify` implementation used in production; `FakeTurnstileVerifier` is
what every test in this repo uses -- deterministic accept/reject, never a
network call.

Verification MUST run before any DB work and before tenant-slug resolution
(app/api/portal.py's ordering) -- verifying after resolving the tenant slug
would let an attacker distinguish "captcha rejected" from "slug doesn't
exist" by timing/response differences, a timing oracle the US-11 review
flagged (Notes: "order CAPTCHA-verify before tenant-slug resolution").
"""

from __future__ import annotations

from typing import Protocol

from app.config import settings

_TURNSTILE_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileVerifier(Protocol):
    async def verify(self, token: str, remote_ip: str | None = None) -> bool: ...


class FakeTurnstileVerifier:
    """Test-only stub. `accept_tokens=None` means "accept only the literal
    string 'valid-test-token'" (a safe default so a test that forgets to
    configure this never accidentally passes); otherwise only tokens in the
    given set are accepted. Never makes a network call."""

    def __init__(self, accept_tokens: set[str] | None = None) -> None:
        self._accept_tokens = accept_tokens

    async def verify(self, token: str, remote_ip: str | None = None) -> bool:
        if not token:
            return False
        if self._accept_tokens is None:
            return token == "valid-test-token"
        return token in self._accept_tokens


class HttpTurnstileVerifier:
    """Production implementation: calls Cloudflare's `siteverify` endpoint.
    NEVER invoked by any test in this repo -- no real Turnstile account
    exists in this environment. The secret key is never exposed via
    `repr()`/`str()` (never logged, per AGENTS.md)."""

    def __init__(self, secret_key: str, timeout_seconds: float = 5.0) -> None:
        self._secret_key = secret_key
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(secret_key=<redacted>)"

    async def verify(self, token: str, remote_ip: str | None = None) -> bool:
        if not token:
            return False

        import httpx

        payload = {"secret": self._secret_key, "response": token}
        if remote_ip:
            payload["remoteip"] = remote_ip

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(_TURNSTILE_SITEVERIFY_URL, data=payload)
        response.raise_for_status()
        data = response.json()
        return bool(data.get("success"))


def get_captcha_verifier() -> TurnstileVerifier:
    """Production wiring, used as a FastAPI dependency default (mirrors
    app.auth.dependencies.get_token_validator). Tests override this via
    FastAPI's dependency_overrides with a FakeTurnstileVerifier."""
    return HttpTurnstileVerifier(secret_key=settings.turnstile_secret_key)
