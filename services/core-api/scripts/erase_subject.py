"""Ops-only right-to-erasure for ONE data subject (US-07, ADR-005).

Runs `app.domain.retention.erasure` for one tenant as the NOBYPASSRLS
`vms_purge` role under that tenant's RLS GUC. A visitor subject is identified
by `--channel/--value`; a staff subject by `--staff-email`. Dry-run is the
DEFAULT. A real run needs `--execute` plus the full guard set. Erasure of an
on-site (CheckedIn/Safe) visitor is refused (DA-B2) -- complete checkout first.

Unifying one person's multiple contacts is out of scope (US-07): this erases
exactly one (channel, value) or one staff email per invocation.

Usage:
    python -m scripts.erase_subject --tenant acme --channel email --value jane@x.example
    python -m scripts.erase_subject --tenant acme --channel email --value jane@x.example \\
        --execute --confirm-tenant acme
    python -m scripts.erase_subject --tenant acme --staff-email bob@x.example \\
        --execute --confirm-tenant acme
"""

from __future__ import annotations

import argparse
import asyncio

from app.crypto.hmac_hash import get_hmac_key_provider
from app.db.purge_session import PurgeSessionLocal, set_purge_tenant
from app.domain.retention.erasure import OnSiteErasureRefused, erase_staff, erase_visitor
from scripts._retention_guards import (
    ActivationRefused,
    assert_execute_authorized,
    resolve_tenant_id,
)


async def _run(args: argparse.Namespace, *, execute: bool) -> dict[str, int]:
    tenant_id = resolve_tenant_id(args.tenant)
    provider = get_hmac_key_provider()
    async with PurgeSessionLocal() as session:
        await set_purge_tenant(session, tenant_id)
        if args.staff_email:
            counts = await erase_staff(
                session, tenant_id, email=args.staff_email, hmac_provider=provider, execute=execute
            )
        else:
            counts = await erase_visitor(
                session, tenant_id, contact_channel=args.channel, contact_value=args.value,
                hmac_provider=provider, execute=execute,
            )
        if execute:
            await session.commit()
        else:
            await session.rollback()
    return counts


def _mask_subject(*, staff_email: str | None, channel: str | None, value: str | None) -> str:
    """A human-recognizable but NON-PII label for console/log output. The raw
    contact / staff email is NEVER echoed: an ops script's stdout may be
    captured to a shared runbook / CI log, and the DoD ("no PII in logs") and
    .claude/rules/security-privacy.md ("Never log PII") apply to that path
    just as much as to the audit row -- which already uses a keyed HMAC. Only
    a single leading character survives, enough for the operator (who typed
    the value) to recognize their own request, not enough to be PII."""
    if staff_email:
        return f"staff:{staff_email[:1]}***"
    return f"{channel}:{value[:1]}***"


def _format(counts: dict[str, int], *, execute: bool, slug: str, subject: str) -> str:
    parts = ", ".join(f"{v} {k}" for k, v in counts.items())
    if execute:
        return f"APPLIED — erased {subject} for {slug}: {parts}"
    return f"DRY RUN — would erase {subject} for {slug}: {parts}; pass --execute --confirm-tenant {slug} to apply"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Right-to-erasure for one data subject.")
    parser.add_argument("--tenant", required=True, help="tenant public_slug")
    parser.add_argument("--channel", help="visitor contact channel (e.g. email); with --value")
    parser.add_argument("--value", help="visitor contact value; with --channel")
    parser.add_argument("--staff-email", help="staff subject email (mutually exclusive with visitor)")
    parser.add_argument("--execute", action="store_true", help="apply (default: dry-run)")
    parser.add_argument("--confirm-tenant", default=None, help="must echo --tenant to --execute")
    args = parser.parse_args(argv)

    is_staff = bool(args.staff_email)
    is_visitor = bool(args.channel and args.value)
    if is_staff == is_visitor:
        parser.error("specify EITHER --staff-email OR both --channel and --value, not both/neither")

    if args.execute:
        try:
            assert_execute_authorized(tenant_slug=args.tenant, confirm_tenant=args.confirm_tenant)
        except ActivationRefused as exc:
            parser.error(str(exc))

    subject = _mask_subject(staff_email=args.staff_email, channel=args.channel, value=args.value)
    try:
        counts = asyncio.run(_run(args, execute=args.execute))
    except OnSiteErasureRefused as exc:
        parser.error(f"erasure refused: {exc}")

    print(_format(counts, execute=args.execute, slug=args.tenant, subject=subject))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
