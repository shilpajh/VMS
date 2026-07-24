"""Task 7 (US-11): Redis-backed token-bucket rate limiting
(app/security/rate_limit.py). Real Redis (docker-compose, REDIS_URL) --
no fake needed for this one, per the story's constraints. Exercises the
token-bucket logic directly with an injected `now` so tests are fast and
deterministic (no real sleeping).
"""

from __future__ import annotations

import uuid

import pytest
import redis.asyncio as redis_async

from app.config import settings
from app.security.rate_limit import TokenBucketRateLimiter, resolve_client_ip


@pytest.fixture()
async def redis_client():
    client = redis_async.from_url(settings.redis_url)
    yield client
    await client.aclose()


def _unique_key() -> str:
    return f"test-rl-{uuid.uuid4().hex}"


async def test_requests_within_capacity_are_allowed(redis_client) -> None:
    limiter = TokenBucketRateLimiter(
        redis_client, capacity=3, refill_per_minute=0.0, key_prefix="test:rl"
    )
    key = _unique_key()

    assert await limiter.check(key, now=1000.0) is True
    assert await limiter.check(key, now=1000.0) is True
    assert await limiter.check(key, now=1000.0) is True


async def test_request_exceeding_burst_capacity_is_rejected(redis_client) -> None:
    limiter = TokenBucketRateLimiter(
        redis_client, capacity=3, refill_per_minute=0.0, key_prefix="test:rl"
    )
    key = _unique_key()

    for _ in range(3):
        assert await limiter.check(key, now=1000.0) is True
    assert await limiter.check(key, now=1000.0) is False


async def test_tokens_refill_over_time(redis_client) -> None:
    # capacity 1, refill 60/min == 1/sec
    limiter = TokenBucketRateLimiter(
        redis_client, capacity=1, refill_per_minute=60.0, key_prefix="test:rl"
    )
    key = _unique_key()

    assert await limiter.check(key, now=2000.0) is True
    assert await limiter.check(key, now=2000.0) is False  # bucket empty, no time passed
    assert await limiter.check(key, now=2001.0) is True  # 1 second later -> 1 token refilled


async def test_different_keys_have_independent_buckets(redis_client) -> None:
    limiter = TokenBucketRateLimiter(
        redis_client, capacity=1, refill_per_minute=0.0, key_prefix="test:rl"
    )
    key_a, key_b = _unique_key(), _unique_key()

    assert await limiter.check(key_a, now=3000.0) is True
    assert await limiter.check(key_a, now=3000.0) is False
    assert await limiter.check(key_b, now=3000.0) is True  # independent bucket, unaffected


def test_forwarded_for_ignored_by_default_when_not_behind_trusted_gateway() -> None:
    resolved = resolve_client_ip(
        remote_addr="203.0.113.5", x_forwarded_for="9.9.9.9", trust_forwarded_for=False
    )
    assert resolved == "203.0.113.5"


def test_forwarded_for_trusted_when_behind_gateway_flag_set() -> None:
    resolved = resolve_client_ip(
        remote_addr="203.0.113.5", x_forwarded_for="9.9.9.9, 10.0.0.1", trust_forwarded_for=True
    )
    assert resolved == "9.9.9.9"  # first hop is the real client


def test_missing_remote_addr_falls_back_to_unknown() -> None:
    resolved = resolve_client_ip(remote_addr=None, x_forwarded_for=None, trust_forwarded_for=False)
    assert resolved == "unknown"
