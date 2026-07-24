"""Task 10 (US-11): visit approval service (app/domain/visits/service.py).

Gherkin Scenario 3 ("Host approval issues a code"). One transaction:
guarded conditional UPDATE (race-safe), check-in code generation (hash
only persisted), one outbox_messages row (envelope-encrypted, deterministic
idempotency key), visit.registered audit.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.crypto.envelope import LocalEnvelopeKeyProvider, decrypt_payload
from app.domain.rbac import PERMISSION_POLICY_VERSION
from app.domain.visits.service import InvalidTransitionError, approve_visit, dispatch_idempotency_key
from app.models import AuditEvent, OutboxMessage, Visit
from tests.conftest import TestAppSessionLocal, insert_tenant, insert_user, set_tenant_context, assign_role


async def _make_requested_visit(session, tenant_id: uuid.UUID, host_user_id: uuid.UUID | None) -> Visit:
    visit = Visit(
        tenant_id=tenant_id,
        status="Requested",
        visitor_full_name="Test Visitor",
        contact_channel="email",
        contact_value="visitor@example.com",
        host_user_id=host_user_id,
        tracking_reference=f"REQ-{uuid.uuid4().int % 10**12:012d}",
        privacy_notice_acknowledged=True,
        privacy_notice_version="v1",
        correlation_id=uuid.uuid4(),
    )
    session.add(visit)
    await session.flush()
    return visit


@pytest.fixture()
def key_provider():
    return LocalEnvelopeKeyProvider()


async def test_approve_transitions_to_registered_and_sets_decision_metadata(app_session, key_provider) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    result = await approve_visit(
        app_session,
        tenant_id=tenant_id,
        visit_id=visit.id,
        actor_user_id=host_user_id,
        key_provider=key_provider,
    )

    assert result.status == "Registered"
    assert result.decided_by_user_id == host_user_id
    assert result.decided_at is not None


async def test_approve_persists_only_the_hash_never_plaintext_code(app_session, key_provider) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    result = await approve_visit(
        app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, key_provider=key_provider
    )

    assert result.checkin_code_hash is not None
    assert len(result.checkin_code_hash) == 64  # sha256 hex digest length

    outbox = (
        await app_session.execute(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == visit.id)
        )
    ).scalar_one()
    decrypted = decrypt_payload(outbox.payload, outbox.payload_key_ref, key_provider)
    import json

    payload = json.loads(decrypted)
    recovered_code_hash = hashlib.sha256(payload["checkin_code"].encode()).hexdigest()
    assert recovered_code_hash == result.checkin_code_hash


async def test_approve_writes_exactly_one_outbox_row_with_deterministic_idempotency_key(
    app_session, key_provider
) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    await approve_visit(
        app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, key_provider=key_provider
    )

    rows = (
        await app_session.execute(select(OutboxMessage).where(OutboxMessage.aggregate_id == visit.id))
    ).scalars().all()
    assert len(rows) == 1
    outbox = rows[0]
    assert outbox.message_type == "visit.checkin_code.dispatch"
    assert outbox.aggregate_type == "visit"
    assert outbox.status == "pending"
    assert outbox.idempotency_key == dispatch_idempotency_key(visit.id)
    assert outbox.not_valid_after is not None
    assert outbox.payload != b""
    assert outbox.correlation_id == visit.correlation_id


async def test_outbox_payload_is_not_cleartext(app_session, key_provider) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    await approve_visit(
        app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, key_provider=key_provider
    )

    outbox = (
        await app_session.execute(select(OutboxMessage).where(OutboxMessage.aggregate_id == visit.id))
    ).scalar_one()
    assert b"visitor@example.com" not in outbox.payload  # contact_value never appears in cleartext


async def test_approve_writes_visit_registered_audit_with_actor_and_policy_version(
    app_session, key_provider
) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    await approve_visit(
        app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, key_provider=key_provider
    )

    audit = (
        await app_session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id, AuditEvent.event_type == "visit.registered"
            )
        )
    ).scalar_one()
    assert audit.actor == str(host_user_id)
    assert audit.target_type == "visit"
    assert audit.target_id == visit.id
    assert audit.correlation_id == visit.correlation_id
    assert audit.policy_version == PERMISSION_POLICY_VERSION


async def test_approve_on_non_requested_visit_raises_invalid_transition(app_session, key_provider) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    await approve_visit(
        app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, key_provider=key_provider
    )

    with pytest.raises(InvalidTransitionError):
        await approve_visit(
            app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, key_provider=key_provider
        )


async def test_concurrent_double_approve_only_one_succeeds() -> None:
    """Race-safety: two concurrent approve calls against the SAME visit ->
    exactly one succeeds (200-equivalent), the other raises
    InvalidTransitionError (409-equivalent). Uses two independent sessions
    (separate connections) to exercise real DB-level concurrency, not just
    in-process serialization."""
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")

    async with TestAppSessionLocal() as setup_session:
        await set_tenant_context(setup_session, tenant_id)
        visit = await _make_requested_visit(setup_session, tenant_id, host_user_id)
        visit_id = visit.id
        await setup_session.commit()

    key_provider = LocalEnvelopeKeyProvider()

    async def _attempt():
        async with TestAppSessionLocal() as session:
            await set_tenant_context(session, tenant_id)
            try:
                await approve_visit(
                    session,
                    tenant_id=tenant_id,
                    visit_id=visit_id,
                    actor_user_id=host_user_id,
                    key_provider=key_provider,
                )
                await session.commit()
                return "ok"
            except InvalidTransitionError:
                await session.rollback()
                return "conflict"

    results = await asyncio.gather(_attempt(), _attempt())
    assert sorted(results) == ["conflict", "ok"]
