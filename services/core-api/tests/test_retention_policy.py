"""Task 3 (US-07): retention resolution -- a tenant's override wins, else the
placeholder config default (app/domain/retention/policy.py).
"""

from __future__ import annotations

import uuid

from app.domain.retention.policy import (
    DEFAULT_RETENTION_SECONDS,
    RetentionCategory,
    resolve_retention,
)
from app.models import RetentionPolicy
from tests.conftest import insert_tenant, set_tenant_context


async def test_default_when_no_override(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    got = await resolve_retention(app_session, tenant_id, RetentionCategory.VISITS)
    assert got == DEFAULT_RETENTION_SECONDS[RetentionCategory.VISITS]


async def test_tenant_override_wins(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    app_session.add(
        RetentionPolicy(tenant_id=tenant_id, data_category="visits", retention_seconds=1234)
    )
    await app_session.flush()
    got = await resolve_retention(app_session, tenant_id, RetentionCategory.VISITS)
    assert got == 1234


async def test_override_is_per_category(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    app_session.add(
        RetentionPolicy(tenant_id=tenant_id, data_category="outbox_messages", retention_seconds=42)
    )
    await app_session.flush()
    assert await resolve_retention(app_session, tenant_id, RetentionCategory.OUTBOX) == 42
    # visits still uses the default (only outbox was overridden)
    assert (
        await resolve_retention(app_session, tenant_id, RetentionCategory.VISITS)
        == DEFAULT_RETENTION_SECONDS[RetentionCategory.VISITS]
    )


def test_every_category_has_a_default() -> None:
    for cat in RetentionCategory:
        assert cat in DEFAULT_RETENTION_SECONDS
        assert DEFAULT_RETENTION_SECONDS[cat] > 0
