"""Task 6 (US-11): public tenant-resolution dependency
(app/auth/public_tenant.py::resolve_public_tenant). Mirrors
app.auth.dependencies.get_current_principal's steps 1-2 (ADR-001 §1) but has
no auth/token/user at all -- a plain dependency for the unauthenticated
portal endpoint. Unknown/suspended slug -> uniform 404 (never leaks which
case it was).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.auth.public_tenant import resolve_public_tenant
from tests.conftest import insert_tenant


async def _set_public_slug(session, tenant_id: uuid.UUID, slug: str) -> None:
    # public_slug can only be set by an ops-role connection in reality
    # (tenant creation/administration is ops-script only, ADR-001 §4) -- but
    # vms_app also has no UPDATE grant on tenants, so this test helper uses
    # the migrator connection directly, mirroring tests/conftest.py's
    # insert_tenant.
    import psycopg2

    from tests.conftest import MIGRATOR_DSN

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET public_slug = %s WHERE id = %s", (slug, str(tenant_id)))
    finally:
        conn.close()


async def test_valid_slug_resolves_tenant_and_sets_guc(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    await _set_public_slug(app_session, tenant_id, slug)

    tenant = await resolve_public_tenant(slug, session=app_session)

    assert tenant.id == tenant_id

    # GUC is set -- a scoped query now succeeds and returns 0 rows (no
    # crash), proving SET LOCAL ran before this point (ADR-001 §1 step 2).
    result = await app_session.execute(text("SELECT 1"))
    assert result.scalar() == 1
    current = await app_session.execute(text("SELECT current_setting('app.current_tenant_id')"))
    assert current.scalar() == str(tenant_id)


async def test_unknown_slug_is_uniform_404(app_session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await resolve_public_tenant(f"no-such-slug-{uuid.uuid4().hex[:8]}", session=app_session)
    assert exc_info.value.status_code == 404


async def test_suspended_tenant_slug_is_uniform_404(app_session) -> None:
    tenant_id = insert_tenant(
        "Suspended Co", f"suspended-entra-tid-{uuid.uuid4().hex[:8]}", status="suspended"
    )
    slug = f"suspended-{uuid.uuid4().hex[:8]}"
    await _set_public_slug(app_session, tenant_id, slug)

    with pytest.raises(HTTPException) as exc_info:
        await resolve_public_tenant(slug, session=app_session)
    assert exc_info.value.status_code == 404


async def test_unknown_and_suspended_slug_produce_the_same_error_detail(app_session) -> None:
    """Anti-enumeration: the two failure modes must be indistinguishable to
    the caller."""
    tenant_id = insert_tenant(
        "Suspended Co", f"suspended2-entra-tid-{uuid.uuid4().hex[:8]}", status="suspended"
    )
    suspended_slug = f"suspended2-{uuid.uuid4().hex[:8]}"
    await _set_public_slug(app_session, tenant_id, suspended_slug)

    with pytest.raises(HTTPException) as unknown_exc:
        await resolve_public_tenant(f"unknown-{uuid.uuid4().hex[:8]}", session=app_session)
    with pytest.raises(HTTPException) as suspended_exc:
        await resolve_public_tenant(suspended_slug, session=app_session)

    assert unknown_exc.value.status_code == suspended_exc.value.status_code == 404
    assert unknown_exc.value.detail == suspended_exc.value.detail
