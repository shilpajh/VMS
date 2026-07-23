"""Async SQLAlchemy session factory for the request path.

Always connects as `vms_app` (settings.database_url) -- the non-superuser,
RLS-subject role (ADR-001 §1). Never used for migrations/ops scripts, which
use the separate `vms_migrator` (BYPASSRLS) role instead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request. This matters beyond convenience: the
    RLS `SET LOCAL app.current_tenant_id` set by
    app.auth.dependencies.get_current_principal is transaction-scoped, so it
    must stay valid for every scoped query the rest of the request makes --
    which requires the whole request to share one transaction, committed
    once at the end (ADR-001 §1)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
