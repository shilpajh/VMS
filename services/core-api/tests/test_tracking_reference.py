"""Task 4 (US-11): tracking-reference generator
(app/domain/visits/tracking_reference.py). `REQ-` + secrets-random 12-digit
numeric; collision-retry on insert; globally unique (visits.tracking_reference
carries a plain UNIQUE constraint, task 2).
"""

from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.visits.tracking_reference import (
    MAX_TRACKING_REFERENCE_ATTEMPTS,
    TrackingReferenceExhaustedError,
    assign_unique_tracking_reference,
    generate_tracking_reference,
)
from app.models import Visit
from tests.conftest import insert_tenant, set_tenant_context

TRACKING_REFERENCE_PATTERN = re.compile(r"^REQ-\d+$")


def test_generated_reference_matches_expected_pattern() -> None:
    ref = generate_tracking_reference()
    assert TRACKING_REFERENCE_PATTERN.match(ref)
    assert len(ref) == len("REQ-") + 12


def test_generated_references_are_not_all_identical() -> None:
    refs = {generate_tracking_reference() for _ in range(20)}
    assert len(refs) > 1


def _new_visit(tenant_id: uuid.UUID) -> Visit:
    return Visit(
        tenant_id=tenant_id,
        status="Requested",
        visitor_full_name="Test Visitor",
        contact_channel="email",
        contact_value="visitor@example.com",
        privacy_notice_acknowledged=True,
        privacy_notice_version="v1",
        correlation_id=uuid.uuid4(),
    )


async def test_assign_unique_tracking_reference_persists_a_valid_reference(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)

    visit = _new_visit(tenant_id)
    await assign_unique_tracking_reference(app_session, visit)

    assert TRACKING_REFERENCE_PATTERN.match(visit.tracking_reference)
    assert visit.id is not None  # flushed


async def test_collision_is_retried_until_a_unique_reference_is_found(app_session, monkeypatch) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)

    existing = _new_visit(tenant_id)
    existing.tracking_reference = "REQ-000000000001"
    app_session.add(existing)
    await app_session.flush()

    colliding_then_unique = iter(["REQ-000000000001", "REQ-000000000002"])
    monkeypatch.setattr(
        "app.domain.visits.tracking_reference.generate_tracking_reference",
        lambda: next(colliding_then_unique),
    )

    visit = _new_visit(tenant_id)
    await assign_unique_tracking_reference(app_session, visit)

    assert visit.tracking_reference == "REQ-000000000002"


async def test_tracking_reference_is_globally_unique_across_tenants(app_session) -> None:
    tenant_a = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    tenant_b = insert_tenant("Globex", f"globex-entra-tid-{uuid.uuid4().hex[:8]}")

    await set_tenant_context(app_session, tenant_a)
    visit_a = _new_visit(tenant_a)
    visit_a.tracking_reference = "REQ-000000000099"
    app_session.add(visit_a)
    await app_session.flush()

    await set_tenant_context(app_session, tenant_b)
    visit_b = _new_visit(tenant_b)
    visit_b.tracking_reference = "REQ-000000000099"
    app_session.add(visit_b)
    with pytest.raises(IntegrityError):
        await app_session.flush()


async def test_exhausting_all_attempts_raises(app_session, monkeypatch) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)

    existing = _new_visit(tenant_id)
    existing.tracking_reference = "REQ-000000000123"
    app_session.add(existing)
    await app_session.flush()

    monkeypatch.setattr(
        "app.domain.visits.tracking_reference.generate_tracking_reference",
        lambda: "REQ-000000000123",  # always collides
    )

    visit = _new_visit(tenant_id)
    with pytest.raises(TrackingReferenceExhaustedError):
        await assign_unique_tracking_reference(app_session, visit)


def test_max_attempts_constant_is_positive() -> None:
    assert MAX_TRACKING_REFERENCE_ATTEMPTS > 1
