"""Task 9 (US-10): audit events on every identity action.

Confirms the 5-field shape (actor, timestamp, policy_version [role changes
only], reason, correlation_id) plus target_type/target_id on every
identity audit event, and that audit_events is append-only at the DB grant
level (no UPDATE/DELETE for vms_app), not just by application convention.
"""

from __future__ import annotations

import uuid

import psycopg2
import psycopg2.errors
import pytest
from sqlalchemy import select

from app.domain.audit import write_audit_event
from app.models import AuditEvent
from tests.conftest import APP_DSN, insert_tenant, set_tenant_context


async def test_write_audit_event_records_all_required_fields(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)

    correlation_id = uuid.uuid4()
    target_id = uuid.uuid4()
    event = await write_audit_event(
        app_session,
        tenant_id=tenant_id,
        event_type="role.assigned",
        actor="oid-actor",
        target_type="user",
        target_id=target_id,
        reason="onboarding",
        correlation_id=correlation_id,
        policy_version="v1",
    )

    assert event.actor == "oid-actor"
    assert event.created_at is not None  # timestamp
    assert event.policy_version == "v1"
    assert event.reason == "onboarding"
    assert event.correlation_id == correlation_id
    assert event.target_type == "user"
    assert event.target_id == target_id


async def test_non_role_change_events_have_no_policy_version(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)

    event = await write_audit_event(
        app_session,
        tenant_id=tenant_id,
        event_type="user.provisioned",
        actor="new-oid",
        target_type="user",
        target_id=uuid.uuid4(),
        reason="first_login_self_provisioning",
        correlation_id=uuid.uuid4(),
    )
    assert event.policy_version is None


@pytest.mark.parametrize(
    "event_type", ["user.provisioned", "user.enabled", "user.disabled", "role.assigned", "role.revoked"]
)
async def test_each_identity_event_type_is_writable_and_queryable(app_session, event_type) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)

    await write_audit_event(
        app_session,
        tenant_id=tenant_id,
        event_type=event_type,
        actor="oid-actor",
        target_type="user",
        target_id=uuid.uuid4(),
        reason="test",
        correlation_id=uuid.uuid4(),
    )

    rows = (
        await app_session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id, AuditEvent.event_type == event_type
            )
        )
    ).scalars().all()
    assert len(rows) == 1


def test_audit_events_are_append_only_no_update_grant() -> None:
    """vms_app has no UPDATE grant on audit_events at all (0001 migration).
    Postgres evaluates the RLS policy's current_setting() call as part of
    planning an UPDATE, so the GUC must be set first, same as any other
    scoped query -- the point of this test is the InsufficientPrivilege
    (missing GRANT), not the RLS fail-closed behavior itself (already
    covered in tests/test_tenant_isolation.py)."""
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    conn = psycopg2.connect(APP_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = %s", (str(tenant_id),))
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    "UPDATE audit_events SET reason = 'tampered' WHERE id = %s",
                    (str(uuid.uuid4()),),
                )
    finally:
        conn.rollback()
        conn.close()


def test_audit_events_are_append_only_no_delete_grant() -> None:
    """Same as above, for DELETE."""
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    conn = psycopg2.connect(APP_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = %s", (str(tenant_id),))
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("DELETE FROM audit_events WHERE id = %s", (str(uuid.uuid4()),))
    finally:
        conn.rollback()
        conn.close()
