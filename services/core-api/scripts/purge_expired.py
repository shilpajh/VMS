"""Ops-only time-based retention purge (US-07, ADR-005).

Runs `app.domain.retention.purge.purge_tenant` for ONE tenant as the
NOBYPASSRLS `vms_purge` role under that tenant's RLS GUC. Dry-run is the
DEFAULT: it reports what WOULD change and mutates nothing. A real run needs
`--execute` plus the full guard set in `_retention_guards` (echoed slug,
activation flag on, non-production env).

Usage:
    python -m scripts.purge_expired --tenant acme
    python -m scripts.purge_expired --tenant acme --execute --confirm-tenant acme
"""

from __future__ import annotations

import argparse
import asyncio

from app.db.purge_session import PurgeSessionLocal, set_purge_tenant
from app.domain.retention.purge import purge_tenant
from scripts._retention_guards import (
    ActivationRefused,
    assert_execute_authorized,
    resolve_tenant_id,
)


async def _run(tenant_slug: str, *, execute: bool) -> dict[str, int]:
    tenant_id = resolve_tenant_id(tenant_slug)
    async with PurgeSessionLocal() as session:
        await set_purge_tenant(session, tenant_id)
        counts = await purge_tenant(session, tenant_id, execute=execute)
        if execute:
            await session.commit()
        else:
            await session.rollback()
    return counts


def _format(counts: dict[str, int], *, execute: bool, slug: str) -> str:
    body = (
        f"scrub {counts.get('visits', 0)} visits, {counts.get('staff_users', 0)} users; "
        f"delete {counts.get('outbox_messages', 0)} outbox, "
        f"{counts.get('contact_verifications', 0)} verifications for {slug}"
    )
    if execute:
        return f"APPLIED — {body}"
    return f"DRY RUN — would {body}; pass --execute --confirm-tenant {slug} to apply"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Time-based retention purge for one tenant.")
    parser.add_argument("--tenant", required=True, help="tenant public_slug")
    parser.add_argument("--execute", action="store_true", help="apply (default: dry-run)")
    parser.add_argument("--confirm-tenant", default=None, help="must echo --tenant to --execute")
    args = parser.parse_args(argv)

    if args.execute:
        try:
            assert_execute_authorized(tenant_slug=args.tenant, confirm_tenant=args.confirm_tenant)
        except ActivationRefused as exc:
            parser.error(str(exc))

    counts = asyncio.run(_run(args.tenant, execute=args.execute))
    print(_format(counts, execute=args.execute, slug=args.tenant))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
