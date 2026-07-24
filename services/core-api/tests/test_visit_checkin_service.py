"""Task 5 (US-01): checkin_visit() domain service
(app/domain/visits/service.py). Gherkin Scenario 1 (happy path), plus the
guarded-UPDATE single-use/race-safety/timing-oracle properties Part A's
Risks section and the design-gate reviews required.

One transaction: guarded UPDATE (hash + tenant + status + expiry all in one
WHERE clause -- no separate post-check step), credential-grant + host-
arrival-notify outbox rows (both envelope-encrypted, per the Blocking fix
both design-gate reviews independently found), `visit.checked_in` audit.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.crypto.envelope import LocalEnvelopeKeyProvider, decrypt_payload
from app.domain.rbac import PERMISSION_POLICY_VERSION
from app.domain.visits.service import (
    InvalidCheckinCodeError,
    arrival_notify_idempotency_key,
    checkin_visit,
    credential_grant_idempotency_key,
)
from app.models import AuditEvent, OutboxMessage, Visit
from tests.conftest import TestAppSessionLocal, insert_tenant, insert_user, set_tenant_context


@pytest.fixture()
def key_provider():
    return LocalEnvelopeKeyProvider()


async def _make_registered_visit(
    session,
    tenant_id: uuid.UUID,
    host_user_id: uuid.UUID,
    *,
    checkin_code: str | None = None,
    expires_delta: timedelta = timedelta(days=7),
    status: str = "Registered",
) -> tuple[Visit, str]:
    code = checkin_code or secrets.token_urlsafe(24)
    visit = Visit(
        tenant_id=tenant_id,
        status=status,
        visitor_full_name="Test Visitor",
        contact_channel="email",
        contact_value="visitor@example.com",
        host_user_id=host_user_id,
        tracking_reference=f"REQ-{uuid.uuid4().int % 10**12:012d}",
        checkin_code_hash=hashlib.sha256(code.encode()).hexdigest(),
        checkin_code_expires_at=datetime.now(timezone.utc) + expires_delta,
        privacy_notice_acknowledged=True,
        privacy_notice_version="v1",
        correlation_id=uuid.uuid4(),
    )
    session.add(visit)
    await session.flush()
    return visit, code


async def test_checkin_transitions_registered_to_checked_in(app_session, key_provider) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    staff_user_id = insert_user(tenant_id, f"oid-reception-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit, code = await _make_registered_visit(app_session, tenant_id, host_user_id)

    result = await checkin_visit(
        app_session,
        tenant_id=tenant_id,
        checkin_code=code,
        actor_user_id=staff_user_id,
        key_provider=key_provider,
    )

    assert result.status == "CheckedIn"
    assert result.checked_in_by_user_id == staff_user_id
    assert result.checked_in_at is not None


async def test_checkin_writes_credential_grant_and_arrival_notify_outbox_rows(
    app_session, key_provider
) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}", email="host@acme.example")
    staff_user_id = insert_user(tenant_id, f"oid-reception-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit, code = await _make_registered_visit(app_session, tenant_id, host_user_id)

    await checkin_visit(
        app_session,
        tenant_id=tenant_id,
        checkin_code=code,
        actor_user_id=staff_user_id,
        key_provider=key_provider,
    )

    rows = (
        await app_session.execute(select(OutboxMessage).where(OutboxMessage.aggregate_id == visit.id))
    ).scalars().all()
    by_type = {row.message_type: row for row in rows}
    assert set(by_type) == {"visit.credential_grant.command", "visit.arrival.notify"}

    grant = by_type["visit.credential_grant.command"]
    assert grant.idempotency_key == credential_grant_idempotency_key(visit.id)
    assert grant.correlation_id == visit.correlation_id
    assert grant.payload_key_ref  # envelope-encrypted, not cleartext

    grant_payload = json.loads(decrypt_payload(grant.payload, grant.payload_key_ref, key_provider))
    assert grant_payload["visit_id"] == str(visit.id)
    assert grant_payload["tenant_id"] == str(tenant_id)
    assert grant_payload["site_id"] is None
    assert grant_payload["device_id"] is None
    assert "zone" not in grant_payload  # dropped from the canonical envelope (ADR-003)
    # No PII in the credential-grant payload -- opaque IDs only.
    assert "visitor_full_name" not in grant_payload
    assert "host_email" not in grant_payload

    notify = by_type["visit.arrival.notify"]
    assert notify.idempotency_key == arrival_notify_idempotency_key(visit.id)
    assert notify.payload_key_ref  # envelope-encrypted -- carries PII

    notify_payload = json.loads(decrypt_payload(notify.payload, notify.payload_key_ref, key_provider))
    assert notify_payload["host_email"] == "host@acme.example"
    assert notify_payload["visitor_full_name"] == "Test Visitor"
    assert notify_payload["tracking_reference"] == visit.tracking_reference


async def test_checkin_outbox_payloads_are_not_cleartext(app_session, key_provider) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}", email="host@acme.example")
    staff_user_id = insert_user(tenant_id, f"oid-reception-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit, code = await _make_registered_visit(app_session, tenant_id, host_user_id)

    await checkin_visit(
        app_session, tenant_id=tenant_id, checkin_code=code, actor_user_id=staff_user_id, key_provider=key_provider
    )

    rows = (
        await app_session.execute(select(OutboxMessage).where(OutboxMessage.aggregate_id == visit.id))
    ).scalars().all()
    for row in rows:
        assert b"host@acme.example" not in row.payload
        assert b"Test Visitor" not in row.payload
        assert str(visit.id).encode() not in row.payload


async def test_checkin_writes_visit_checked_in_audit_with_actor_reason_qr_and_policy_version(
    app_session, key_provider
) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    staff_user_id = insert_user(tenant_id, f"oid-reception-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit, code = await _make_registered_visit(app_session, tenant_id, host_user_id)

    await checkin_visit(
        app_session, tenant_id=tenant_id, checkin_code=code, actor_user_id=staff_user_id, key_provider=key_provider
    )

    audit = (
        await app_session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id, AuditEvent.event_type == "visit.checked_in"
            )
        )
    ).scalar_one()
    assert audit.actor == str(staff_user_id)
    assert audit.target_type == "visit"
    assert audit.target_id == visit.id
    assert audit.correlation_id == visit.correlation_id
    assert audit.reason == "qr"  # coded stand-in for the contract's verification_method field
    assert audit.policy_version == PERMISSION_POLICY_VERSION
    # No field/value here may imply a watchlist check was performed/cleared.
    assert "watchlist" not in audit.reason.lower()


async def test_checkin_calls_watchlist_clear_and_identity_verified_guards(app_session, key_provider) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    staff_user_id = insert_user(tenant_id, f"oid-reception-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit, code = await _make_registered_visit(app_session, tenant_id, host_user_id)

    with (
        patch("app.domain.visits.service.watchlist_clear", wraps=None, return_value=True) as watchlist_mock,
        patch(
            "app.domain.visits.service.identity_verified_by_code", wraps=None, return_value=True
        ) as identity_mock,
    ):
        await checkin_visit(
            app_session,
            tenant_id=tenant_id,
            checkin_code=code,
            actor_user_id=staff_user_id,
            key_provider=key_provider,
        )

    watchlist_mock.assert_called_once()
    identity_mock.assert_called_once()


async def test_checkin_with_unknown_code_raises_invalid_checkin_code_error(app_session, key_provider) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    staff_user_id = insert_user(tenant_id, f"oid-reception-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit, _code = await _make_registered_visit(app_session, tenant_id, host_user_id)

    with pytest.raises(InvalidCheckinCodeError):
        await checkin_visit(
            app_session,
            tenant_id=tenant_id,
            checkin_code=secrets.token_urlsafe(24),  # never matches
            actor_user_id=staff_user_id,
            key_provider=key_provider,
        )

    refreshed = (await app_session.execute(select(Visit).where(Visit.id == visit.id))).scalar_one()
    assert refreshed.status == "Registered"


async def test_checkin_with_expired_code_raises_invalid_checkin_code_error_and_no_side_effects(
    app_session, key_provider
) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    staff_user_id = insert_user(tenant_id, f"oid-reception-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit, code = await _make_registered_visit(
        app_session, tenant_id, host_user_id, expires_delta=timedelta(seconds=-1)
    )

    with pytest.raises(InvalidCheckinCodeError):
        await checkin_visit(
            app_session, tenant_id=tenant_id, checkin_code=code, actor_user_id=staff_user_id, key_provider=key_provider
        )

    refreshed = (await app_session.execute(select(Visit).where(Visit.id == visit.id))).scalar_one()
    assert refreshed.status == "Registered"  # never flipped, not flipped-then-rolled-back

    outbox_rows = (
        await app_session.execute(select(OutboxMessage).where(OutboxMessage.aggregate_id == visit.id))
    ).scalars().all()
    assert outbox_rows == []
    audit_rows = (
        await app_session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id, AuditEvent.target_id == visit.id
            )
        )
    ).scalars().all()
    assert audit_rows == []


async def test_checkin_wrong_tenant_code_raises_invalid_checkin_code_error(app_session, key_provider) -> None:
    victim_tenant_id = insert_tenant("Victim Co", f"victim-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(victim_tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, victim_tenant_id)
    visit, code = await _make_registered_visit(app_session, victim_tenant_id, host_user_id)
    await app_session.commit()

    attacker_tenant_id = insert_tenant("Attacker Co", f"attacker-entra-tid-{uuid.uuid4().hex[:8]}")
    attacker_staff_id = insert_user(attacker_tenant_id, f"oid-reception-{uuid.uuid4().hex[:8]}")

    async with TestAppSessionLocal() as attacker_session:
        await set_tenant_context(attacker_session, attacker_tenant_id)
        with pytest.raises(InvalidCheckinCodeError):
            await checkin_visit(
                attacker_session,
                tenant_id=attacker_tenant_id,
                checkin_code=code,
                actor_user_id=attacker_staff_id,
                key_provider=key_provider,
            )
        await attacker_session.rollback()

    # SET LOCAL is transaction-scoped -- the earlier app_session.commit()
    # ended that transaction, so the tenant GUC must be set again for this
    # verification query.
    await set_tenant_context(app_session, victim_tenant_id)
    refreshed = (
        await app_session.execute(select(Visit).where(Visit.id == visit.id))
    ).scalar_one()
    assert refreshed.status == "Registered"


async def test_checkin_replay_after_checked_in_raises_invalid_checkin_code_error(
    app_session, key_provider
) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    staff_user_id = insert_user(tenant_id, f"oid-reception-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit, code = await _make_registered_visit(app_session, tenant_id, host_user_id)

    await checkin_visit(
        app_session, tenant_id=tenant_id, checkin_code=code, actor_user_id=staff_user_id, key_provider=key_provider
    )

    with pytest.raises(InvalidCheckinCodeError):
        await checkin_visit(
            app_session, tenant_id=tenant_id, checkin_code=code, actor_user_id=staff_user_id, key_provider=key_provider
        )


async def test_concurrent_double_checkin_only_one_succeeds() -> None:
    """Race-safety, mirroring test_visit_approval_outbox.py's precedent:
    two concurrent checkin_visit() calls against the SAME code -> exactly
    one succeeds, the other raises InvalidCheckinCodeError."""
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    staff_user_id = insert_user(tenant_id, f"oid-reception-{uuid.uuid4().hex[:8]}")

    async with TestAppSessionLocal() as setup_session:
        await set_tenant_context(setup_session, tenant_id)
        visit, code = await _make_registered_visit(setup_session, tenant_id, host_user_id)
        visit_id = visit.id
        await setup_session.commit()

    key_provider = LocalEnvelopeKeyProvider()

    async def _attempt():
        async with TestAppSessionLocal() as session:
            await set_tenant_context(session, tenant_id)
            try:
                await checkin_visit(
                    session,
                    tenant_id=tenant_id,
                    checkin_code=code,
                    actor_user_id=staff_user_id,
                    key_provider=key_provider,
                )
                await session.commit()
                return "ok"
            except InvalidCheckinCodeError:
                await session.rollback()
                return "conflict"

    results = await asyncio.gather(_attempt(), _attempt())
    assert sorted(results) == ["conflict", "ok"]
    assert visit_id  # keep linters happy about unused var across gather scope
