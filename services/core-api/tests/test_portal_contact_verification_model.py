"""Task 2 (US-13a): PortalContactVerification model + new Visit columns
round-trip against the real vms_test schema (at head, incl. 0004).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import PortalContactVerification, Visit
from tests.conftest import insert_tenant, set_tenant_context


async def test_portal_contact_verification_round_trips(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)

    row = PortalContactVerification(
        tenant_id=tenant_id,
        contact_channel="email",
        contact_value="jane@example.com",
        otp_hash="a" * 64,
        otp_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        privacy_notice_acknowledged=True,
        privacy_notice_version="v1",
    )
    app_session.add(row)
    await app_session.flush()

    fetched = (
        await app_session.execute(
            select(PortalContactVerification).where(PortalContactVerification.id == row.id)
        )
    ).scalar_one()
    assert fetched.otp_attempts == 0
    assert fetched.superseded is False
    assert fetched.consumed_at is None
    assert fetched.verification_token_hash is None


async def test_visit_new_portal_columns_round_trip(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)

    visit = Visit(
        tenant_id=tenant_id,
        status="Requested",
        visitor_full_name="Jane Visitor",
        contact_channel="email",
        contact_value="jane@example.com",
        tracking_reference=f"REQ-{uuid.uuid4().int % 10**12:012d}",
        privacy_notice_version="v1",
        correlation_id=uuid.uuid4(),
        purpose="Business meeting",
        group_type="group",
        expected_group_size=3,
        identity_verification_choice="send_to_host",
        contact_verified=True,
    )
    app_session.add(visit)
    await app_session.flush()

    fetched = (await app_session.execute(select(Visit).where(Visit.id == visit.id))).scalar_one()
    assert fetched.purpose == "Business meeting"
    assert fetched.group_type == "group"
    assert fetched.expected_group_size == 3
    assert fetched.identity_verification_choice == "send_to_host"
    assert fetched.contact_verified is True


async def test_visit_contact_verified_defaults_false(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = Visit(
        tenant_id=tenant_id,
        status="Requested",
        visitor_full_name="No Portal Fields",
        contact_channel="email",
        contact_value="x@example.com",
        tracking_reference=f"REQ-{uuid.uuid4().int % 10**12:012d}",
        privacy_notice_version="v1",
        correlation_id=uuid.uuid4(),
    )
    app_session.add(visit)
    await app_session.flush()
    await app_session.refresh(visit)
    assert visit.contact_verified is False
