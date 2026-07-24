"""Redis-backed token-bucket rate limiting for the public portal router
(US-11, task 7).

Real Redis (docker-compose, `settings.redis_url`) -- no fake needed for
this one dependency, unlike Turnstile/Key Vault (no vendor credential
involved, just the already-running local Redis).

Two independent buckets guard the public submission endpoint (per the API
contract delta): per-IP (sustained ~5/min, burst up to 10) and
per-tenant-slug (sustained ~60/min) -- both enforced before any DB work,
right after CAPTCHA verification (app/api/portal.py).

`X-Forwarded-For` is trusted ONLY when `settings.trust_forwarded_for` is
set (default False for local dev) -- otherwise a client could set this
header itself to spoof its source IP and evade the per-IP bucket entirely.
"""

from __future__ import annotations

import time

import redis.asyncio as redis_async
from fastapi import Depends, HTTPException, Request, status

from app.config import settings

# Atomic Lua token-bucket check-and-consume: refills `tokens` by
# `refill_per_second * elapsed` since the bucket's last-seen timestamp (capped
# at `capacity`), then consumes 1 token if available. Single EVAL call so the
# read-modify-write is atomic under concurrent requests (no separate GET/SET
# race).
_TOKEN_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local refill_per_second = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(bucket[1])
local ts = tonumber(bucket[2])

if tokens == nil then
  tokens = capacity
  ts = now
end

local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * refill_per_second)

local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end

redis.call('HMSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('EXPIRE', KEYS[1], 3600)

return allowed
"""


class TokenBucketRateLimiter:
    def __init__(
        self,
        redis_client: redis_async.Redis,
        *,
        capacity: int,
        refill_per_minute: float,
        key_prefix: str,
    ) -> None:
        self._redis = redis_client
        self._capacity = capacity
        self._refill_per_second = refill_per_minute / 60.0
        self._key_prefix = key_prefix

    async def check(self, key: str, *, now: float | None = None) -> bool:
        """Returns True (and consumes a token) if the request is allowed
        under `key`'s bucket, False if the bucket is empty (rate-limited)."""
        if now is None:
            now = time.time()
        bucket_key = f"{self._key_prefix}:{key}"
        allowed = await self._redis.eval(
            _TOKEN_BUCKET_LUA, 1, bucket_key, self._capacity, self._refill_per_second, now
        )
        return bool(allowed)


def resolve_client_ip(
    *, remote_addr: str | None, x_forwarded_for: str | None, trust_forwarded_for: bool
) -> str:
    if trust_forwarded_for and x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return remote_addr or "unknown"


_redis_client: redis_async.Redis | None = None


def get_redis_client() -> redis_async.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_async.from_url(settings.redis_url)
    return _redis_client


def get_per_ip_rate_limiter(
    redis_client: redis_async.Redis = Depends(get_redis_client),
) -> TokenBucketRateLimiter:
    return TokenBucketRateLimiter(
        redis_client,
        capacity=settings.portal_rate_limit_per_ip_capacity,
        refill_per_minute=settings.portal_rate_limit_per_ip_refill_per_minute,
        key_prefix="ratelimit:portal:ip",
    )


def get_per_tenant_rate_limiter(
    redis_client: redis_async.Redis = Depends(get_redis_client),
) -> TokenBucketRateLimiter:
    return TokenBucketRateLimiter(
        redis_client,
        capacity=settings.portal_rate_limit_per_tenant_capacity,
        refill_per_minute=settings.portal_rate_limit_per_tenant_refill_per_minute,
        key_prefix="ratelimit:portal:tenant",
    )


# --- US-13a: dedicated buckets, each on its OWN Redis key namespace so a
# flood on one surface can never drain another's budget (US-13 review
# Should-fix #5). OTP endpoints are stricter than submission; tracking
# lookup is a read and is more generous, but still separate.
def get_otp_request_ip_limiter(
    redis_client: redis_async.Redis = Depends(get_redis_client),
) -> TokenBucketRateLimiter:
    return TokenBucketRateLimiter(
        redis_client,
        capacity=settings.otp_request_per_ip_capacity,
        refill_per_minute=settings.otp_request_per_ip_refill_per_minute,
        key_prefix="ratelimit:portal:otp_request:ip",
    )


def get_otp_request_contact_limiter(
    redis_client: redis_async.Redis = Depends(get_redis_client),
) -> TokenBucketRateLimiter:
    return TokenBucketRateLimiter(
        redis_client,
        capacity=settings.otp_request_per_contact_capacity,
        refill_per_minute=settings.otp_request_per_contact_refill_per_minute,
        key_prefix="ratelimit:portal:otp_request:contact",
    )


def get_otp_verify_ip_limiter(
    redis_client: redis_async.Redis = Depends(get_redis_client),
) -> TokenBucketRateLimiter:
    return TokenBucketRateLimiter(
        redis_client,
        capacity=settings.otp_verify_per_ip_capacity,
        refill_per_minute=settings.otp_verify_per_ip_refill_per_minute,
        key_prefix="ratelimit:portal:otp_verify:ip",
    )


def get_tracking_lookup_ip_limiter(
    redis_client: redis_async.Redis = Depends(get_redis_client),
) -> TokenBucketRateLimiter:
    return TokenBucketRateLimiter(
        redis_client,
        capacity=settings.tracking_lookup_per_ip_capacity,
        refill_per_minute=settings.tracking_lookup_per_ip_refill_per_minute,
        key_prefix="ratelimit:portal:lookup:ip",
    )


def get_tracking_lookup_tenant_limiter(
    redis_client: redis_async.Redis = Depends(get_redis_client),
) -> TokenBucketRateLimiter:
    return TokenBucketRateLimiter(
        redis_client,
        capacity=settings.tracking_lookup_per_tenant_capacity,
        refill_per_minute=settings.tracking_lookup_per_tenant_refill_per_minute,
        key_prefix="ratelimit:portal:lookup:tenant",
    )


async def enforce_public_rate_limits(
    request: Request,
    tenant_slug: str,
    per_ip_limiter: TokenBucketRateLimiter = Depends(get_per_ip_rate_limiter),
    per_tenant_limiter: TokenBucketRateLimiter = Depends(get_per_tenant_rate_limiter),
) -> None:
    """FastAPI dependency: raises 429 if either the per-IP or the
    per-tenant-slug bucket is exhausted. Keyed on the raw path slug string
    -- no tenant DB lookup needed, so this can run before tenant resolution
    (app/api/portal.py's ordering)."""
    client_ip = resolve_client_ip(
        remote_addr=request.client.host if request.client else None,
        x_forwarded_for=request.headers.get("x-forwarded-for"),
        trust_forwarded_for=settings.trust_forwarded_for,
    )
    if not await per_ip_limiter.check(client_ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded")
    if not await per_tenant_limiter.check(tenant_slug):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded")
