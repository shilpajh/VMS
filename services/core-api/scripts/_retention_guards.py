"""Shared ops-CLI guards for the retention scripts (US-07, ADR-005).

Both `purge_expired` and `erase_subject` are irreversible. The guards here
are the human-gated-activation fence (Constraint 2): an `--execute` run only
proceeds when ALL of these hold, so no single misconfiguration can trigger a
real purge --

  1. `--execute` is explicitly passed (dry-run is the default),
  2. `--confirm-tenant <slug>` echoes back the exact target slug,
  3. `settings.retention_purge_enabled` is True (compliance-owner flip),
  4. `settings.app_environment` is not "production".

Kept out of the domain layer on purpose: these are operator-safety controls
on the CLI, not business rules. The domain functions stay callable with
`execute=True` from tests without needing this ceremony.
"""

from __future__ import annotations

import uuid

import psycopg2

from app.config import settings

# Sync (psycopg2) DSN for the one-off tenant-slug lookup -- resolved via the
# purge role too, but RLS is not applicable to the tenants table (ADR-001 §2),
# so this read sees the whole tenant catalog to map slug -> id.
_SYNC_PURGE_DSN = settings.purge_database_url.replace("+asyncpg", "")


class ActivationRefused(Exception):
    """Raised when an --execute run is not fully authorized (missing
    confirmation, disabled flag, or a production environment)."""


def resolve_tenant_id(slug: str) -> uuid.UUID:
    """Map a tenant public_slug to its id. Raises if no such tenant."""
    conn = psycopg2.connect(_SYNC_PURGE_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tenants WHERE public_slug = %s", (slug,))
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise ActivationRefused(f"no tenant with public_slug={slug!r}")
    return row[0]


def assert_execute_authorized(*, tenant_slug: str, confirm_tenant: str | None) -> None:
    """Enforce guards 2-4 (guard 1, `--execute` present, is the caller's
    branch). Raises ActivationRefused with an actionable message otherwise."""
    if confirm_tenant != tenant_slug:
        raise ActivationRefused(
            f"--confirm-tenant must exactly echo the target slug ({tenant_slug!r}) to --execute; "
            f"got {confirm_tenant!r}"
        )
    if settings.app_environment == "production":
        raise ActivationRefused(
            "refusing to --execute in a production environment from an ops script; "
            "production retention runs are a separately human-gated operation"
        )
    if not settings.retention_purge_enabled:
        raise ActivationRefused(
            "retention_purge_enabled is False -- the mechanism is built but not activated; "
            "a compliance owner must ratify the retention windows and flip it on first"
        )
