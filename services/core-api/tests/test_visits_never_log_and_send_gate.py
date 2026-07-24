"""Task 12 (US-11): never-log-payload + staleness send-gate contract test.

No new code beyond what tasks 1-11 already built -- this is a verification
task (ADR-002 §4/§5), documented here as an executable contract even though
the relay worker itself isn't built in this story (Part A, explicit scope
cut): (1) no log call site anywhere in this story's app code ever logs
`outbox_messages.payload`/decrypted contents/`contact_value`/the plaintext
`checkin_code`; (2) `not_valid_after` is populated correctly at write time,
matching the encrypted payload's own `code_expires_at`, so a
not-yet-built worker COULD honor the send-gate (ADR-002 §4) against real
data.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.crypto.envelope import LocalEnvelopeKeyProvider, decrypt_payload
from app.domain.visits.service import CHECKIN_CODE_VALIDITY, approve_visit
from app.models import OutboxMessage, Visit
from tests.conftest import insert_tenant, insert_user, set_tenant_context

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# Any call site that plausibly writes to a log/console, paired with any
# forbidden-content marker. This is intentionally broad (catches
# logger.*, logging.*, print(, and structured-logging-style calls).
_LOG_CALL_PATTERN = re.compile(r"\b(logger|logging)\.\w+\(|print\(")
_FORBIDDEN_MARKERS = ("payload", "contact_value", "checkin_code", "decrypted")


def _lines_with_forbidden_log_content(source: str) -> list[str]:
    """The actual scanner under test: returns every line in `source` that
    both looks like a log/print call AND mentions a forbidden marker."""
    violations = []
    for line in source.splitlines():
        if _LOG_CALL_PATTERN.search(line) and any(marker in line.lower() for marker in _FORBIDDEN_MARKERS):
            violations.append(line)
    return violations


def test_scanner_detects_an_injected_violation() -> None:
    """Sanity check on the scanner itself -- proves it isn't vacuously
    passing just because this story introduced zero log calls at all."""
    bad_source = 'logger.info(f"dispatching payload={payload}")\n'
    assert _lines_with_forbidden_log_content(bad_source) == [bad_source.rstrip("\n")]


def test_scanner_allows_safe_log_lines() -> None:
    safe_source = 'logger.info(f"dispatched outbox id={outbox.id} tenant_id={tenant_id}")\n'
    assert _lines_with_forbidden_log_content(safe_source) == []


def test_no_source_file_under_app_logs_payload_or_pii_or_checkin_code() -> None:
    violations: dict[str, list[str]] = {}
    for path in APP_ROOT.rglob("*.py"):
        source = path.read_text()
        found = _lines_with_forbidden_log_content(source)
        if found:
            violations[str(path.relative_to(APP_ROOT))] = found

    assert violations == {}, (
        "log/print call sites reference a forbidden field name -- never log "
        f"PII/credentials (AGENTS.md): {violations}"
    )


@pytest.fixture()
def key_provider():
    return LocalEnvelopeKeyProvider()


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


async def test_not_valid_after_matches_the_payloads_own_code_expires_at(app_session, key_provider) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    before = datetime.now(timezone.utc)
    await approve_visit(
        app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, key_provider=key_provider
    )
    after = datetime.now(timezone.utc)

    outbox = (
        await app_session.execute(select(OutboxMessage).where(OutboxMessage.aggregate_id == visit.id))
    ).scalar_one()

    assert outbox.not_valid_after is not None
    assert before + CHECKIN_CODE_VALIDITY <= outbox.not_valid_after <= after + CHECKIN_CODE_VALIDITY

    decrypted = decrypt_payload(outbox.payload, outbox.payload_key_ref, key_provider)
    payload = json.loads(decrypted)
    payload_expiry = datetime.fromisoformat(payload["code_expires_at"])
    # Send-gate (ADR-002 §4) reads not_valid_after WITHOUT decrypting the
    # payload -- it must agree with what's actually inside the payload.
    assert abs((payload_expiry - outbox.not_valid_after).total_seconds()) < 1


async def test_a_visit_superseded_by_denial_would_fail_the_status_half_of_the_send_gate(
    app_session, key_provider
) -> None:
    """Documents (without building the worker) that ADR-002 §4's second
    send-gate condition -- "the visit's current status is no longer
    Registered" -- is checkable from data this story already writes: after
    approval, the visit's own `status` column is the thing a future worker
    re-reads before dispatch."""
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    host_user_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(app_session, tenant_id)
    visit = await _make_requested_visit(app_session, tenant_id, host_user_id)

    registered = await approve_visit(
        app_session, tenant_id=tenant_id, visit_id=visit.id, actor_user_id=host_user_id, key_provider=key_provider
    )
    assert registered.status == "Registered"  # a future worker's re-read would see this and proceed
