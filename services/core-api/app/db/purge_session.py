"""Async session factory for the retention purge / erasure (US-07, ADR-005).

Connects as the dedicated NOBYPASSRLS `vms_purge` role
(settings.purge_database_url). Because that role is *subject to* RLS+FORCE,
every statement the purge/erasure runs is structurally scoped to whichever
tenant `set_purge_tenant` has set the GUC to -- a forgotten tenant predicate
cannot leak across tenants (SP-B2). This is deliberately a separate role from
both `vms_app` (request path) and `vms_migrator` (BYPASSRLS migrations): an
irreversible cross-tenant DELETE must not run with RLS bypassed.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

purge_engine = create_async_engine(settings.purge_database_url, pool_pre_ping=True)
PurgeSessionLocal = async_sessionmaker(purge_engine, expire_on_commit=False)


async def set_purge_tenant(session: AsyncSession, tenant_id) -> None:
    """Set the per-tenant RLS GUC for this transaction. `tenant_id` is always
    a UUID the ops script resolved from the DB (a tenant slug lookup), never
    raw free-form input, so the interpolation here cannot inject."""
    await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
