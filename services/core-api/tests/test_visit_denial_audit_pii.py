"""Task 10 (US-11): visit denial service (app/domain/visits/service.py).

Gherkin Scenario 4 ("Host denial is recorded with reason"), reconciled per
the US-11 plan's Definition of Done / Risks: the audit `reason` is a CODED
value + a `visits.id` reference, never the host's free-text verbatim (US-11
review, Should-fix #2) -- the free text lives only on the purgeable
`visits.denial_reason` column.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.domain.rbac import PERMISSION_POLICY_VERSION
from app.domain.visits.service import InvalidTransitionError, deny_visit
from app.models import AuditEvent, OutboxMessage, Visit
from tests.conftest import insert_tenant, insert_user, set_tenant_context

FREE_TEXT_REASON = "unknown visitor -- looked suspicious, refused ID"


async def _make_requested_visit(session, tenant_id: uuid.UUID, host_user_id: uuid.UUID) -> Visit:
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


async def test_deny_transitions_to_denied_and_stores_free_text_reason_on_visit(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    result = await deny_visit(
        app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, reason=FREE_TEXT_REASON
    )

    assert result.status == "Denied"
    assert result.denial_reason == FREE_TEXT_REASON
    assert result.decided_by_user_id == host_user_id


async def test_deny_creates_no_credential_and_no_outbox_row(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    result = await deny_visit(
        app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, reason=FREE_TEXT_REASON
    )

    assert result.checkin_code_hash is None
    outbox_rows = (
        await app_session.execute(select(OutboxMessage).where(OutboxMessage.aggregate_id == visit.id))
    ).scalars().all()
    assert outbox_rows == []


async def test_deny_audit_reason_is_coded_never_the_free_text_verbatim(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    await deny_visit(
        app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, reason=FREE_TEXT_REASON
    )

    audit = (
        await app_session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id, AuditEvent.event_type == "visit.denied"
            )
        )
    ).scalar_one()

    assert audit.reason != FREE_TEXT_REASON
    assert "suspicious" not in audit.reason  # no fragment of the free text leaks either
    assert audit.target_type == "visit"
    assert audit.target_id == visit.id
    assert audit.actor == str(host_user_id)
    assert audit.policy_version == PERMISSION_POLICY_VERSION


async def test_deny_requires_non_empty_reason(app_session) -> None:
    """The 422-on-missing-reason contract lives at the API layer (task 11,
    VisitDenyRequest's Field(min_length=1)); the domain service itself
    still defends against being called with an empty reason directly, so a
    future caller that skips the DTO can never persist a blank reason."""
    from app.domain.visits.service import EmptyDenialReasonError

    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    with pytest.raises(EmptyDenialReasonError):
        await deny_visit(app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, reason="")


async def test_deny_on_non_requested_visit_raises_invalid_transition(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    await deny_visit(
        app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, reason=FREE_TEXT_REASON
    )

    with pytest.raises(InvalidTransitionError):
        await deny_visit(
            app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, reason="second attempt"
        )
