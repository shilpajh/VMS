"""Tracking-reference generation (US-11, task 4).

`"REQ-"` + a `secrets`-random 12-digit numeric suffix. Globally unique
(`visits.tracking_reference` carries a plain UNIQUE constraint, task 2) --
"globally" here means across all tenants, not per-tenant, since the
tracking reference is the only thing an anonymous visitor holds and it must
never collide regardless of which tenant it belongs to.

`assign_unique_tracking_reference` proves uniqueness the only way that's
actually safe under concurrency: an actual DB insert attempt, retried on a
UNIQUE-constraint collision. Each attempt runs inside its own SAVEPOINT
(`session.begin_nested()`) so a collision only rolls back this one attempt,
not the whole request's transaction -- which matters because the portal
submission's transaction may already have an earlier `SET LOCAL
app.current_tenant_id` in effect (ADR-001 §1) that must survive the retry.
"""

from __future__ import annotations

import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Visit

MAX_TRACKING_REFERENCE_ATTEMPTS = 5


class TrackingReferenceExhaustedError(Exception):
    """Raised when every collision-retry attempt was exhausted without
    finding a unique tracking_reference. Should be effectively unreachable
    in production (12 numeric digits is 10^12 keyspace); a real occurrence
    indicates something is badly wrong (e.g. a broken random source) and
    must not be silently swallowed."""


def generate_tracking_reference() -> str:
    return f"REQ-{secrets.randbelow(10**12):012d}"


async def assign_unique_tracking_reference(session: AsyncSession, visit: Visit) -> None:
    """Sets `visit.tracking_reference` to a value proven unique by a real
    insert, adding `visit` to the session and flushing it. Raises
    TrackingReferenceExhaustedError if every attempt collided."""
    for _ in range(MAX_TRACKING_REFERENCE_ATTEMPTS):
        visit.tracking_reference = generate_tracking_reference()
        try:
            async with session.begin_nested():
                session.add(visit)
                await session.flush()
            return
        except IntegrityError:
            continue
    raise TrackingReferenceExhaustedError(
        f"failed to generate a unique tracking_reference after "
        f"{MAX_TRACKING_REFERENCE_ATTEMPTS} attempts"
    )
