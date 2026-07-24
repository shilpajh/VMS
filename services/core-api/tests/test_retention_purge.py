"""Task 4 (US-07): time-based purge. Synthetic data only. Exercises the
purge as the NOBYPASSRLS `vms_purge` role with a per-tenant GUC, so the
structural-isolation guarantee (SP-B2) is what's actually tested.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest
from sqlalchemy import select

from app.domain.retention.purge import purge_tenant
from app.models import AuditEvent, OutboxMessage, PortalContactVerification, User, Visit
from tests.conftest import (
    MIGRATOR_DSN,
    TestPurgeSessionLocal,
    insert_tenant,
    set_tenant_context,
)

NOW = datetime.now(timezone.utc)
OLD = NOW - timedelta(days=200)   # expired for every window
FRESH = NOW - timedelta(hours=1)  # fresh for every window


def _mig():
    conn = psycopg2.connect(MIGRATOR_DSN)
    conn.autocommit = True
    return conn


def _seed_visit(tenant_id, *, status, created_at, decided_at=None) -> uuid.UUID:
    vid = uuid.uuid4()
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO visits (id, tenant_id, status, visitor_full_name, contact_channel, "
            "contact_value, host_hint, purpose, tracking_reference, denial_reason, "
            "privacy_notice_version, correlation_id, created_at, decided_at) "
            "VALUES (%s,%s,%s,'Jane Real','email','jane@real.example','Rahul','Legal meeting re: X',"
            "%s,'because reasons','v1',%s,%s,%s)",
            (str(vid), str(tenant_id), status, f"REQ-{uuid.uuid4().int % 10**12:012d}",
             str(uuid.uuid4()), created_at, decided_at),
        )
    return vid


def _seed_disabled_user(tenant_id, *, disabled_at) -> uuid.UUID:
    uid = uuid.uuid4()
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, tenant_id, external_idp_subject, email, display_name, status, disabled_at) "
            "VALUES (%s,%s,%s,%s,'Real Name','disabled',%s)",
            (str(uid), str(tenant_id), f"oid-{uuid.uuid4().hex[:8]}", f"real-{uuid.uuid4().hex[:6]}@x.example", disabled_at),
        )
    return uid


def _seed_outbox(tenant_id, *, created_at) -> uuid.UUID:
    oid = uuid.uuid4()
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO outbox_messages (id, tenant_id, message_type, aggregate_type, aggregate_id, "
            "correlation_id, idempotency_key, payload, payload_key_ref, status, created_at) "
            "VALUES (%s,%s,'visit.checkin_code.dispatch','visit',%s,%s,%s,%s,'k','dispatched',%s)",
            (str(oid), str(tenant_id), str(uuid.uuid4()), str(uuid.uuid4()),
             uuid.uuid4().hex, b"cipher", created_at),
        )
    return oid


def _seed_cv(tenant_id, *, created_at) -> uuid.UUID:
    cid = uuid.uuid4()
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO portal_contact_verifications (id, tenant_id, contact_channel, contact_value, "
            "otp_hash, otp_expires_at, privacy_notice_version, created_at) "
            "VALUES (%s,%s,'email','jane@real.example','h',%s,'v1',%s)",
            (str(cid), str(tenant_id), NOW + timedelta(minutes=5), created_at),
        )
    return cid


def _visit_row(vid):
    with _mig() as conn, conn.cursor() as cur:
        cur.execute("SELECT visitor_full_name, contact_value, purpose, purged_at FROM visits WHERE id=%s", (str(vid),))
        return cur.fetchone()


def _exists(table, rid):
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {table} WHERE id=%s", (str(rid),))
        return cur.fetchone() is not None


async def _purge(tenant_id, *, execute):
    async with TestPurgeSessionLocal() as s:
        await set_tenant_context(s, tenant_id)
        counts = await purge_tenant(s, tenant_id, execute=execute)
        await s.commit()
        return counts


@pytest.fixture()
def tenant():
    return insert_tenant("Acme", f"acme-{uuid.uuid4().hex[:8]}")


async def test_expired_visits_scrubbed_fresh_untouched(tenant) -> None:
    expired_denied = _seed_visit(tenant, status="Denied", created_at=OLD, decided_at=OLD)
    expired_abandoned = _seed_visit(tenant, status="Requested", created_at=OLD)
    fresh = _seed_visit(tenant, status="Denied", created_at=FRESH, decided_at=FRESH)
    onsite = _seed_visit(tenant, status="CheckedIn", created_at=OLD)

    counts = await _purge(tenant, execute=True)
    assert counts["visits"] == 2  # denied + abandoned, not fresh, not on-site

    for vid in (expired_denied, expired_abandoned):
        name, contact, purpose, purged_at = _visit_row(vid)
        assert name == "[redacted]" and contact == "[redacted]" and purpose is None
        assert purged_at is not None
    # fresh and on-site keep their real PII
    assert _visit_row(fresh)[0] == "Jane Real"
    assert _visit_row(onsite)[0] == "Jane Real"


async def test_expired_users_scrubbed_with_unique_markers(tenant) -> None:
    u1 = _seed_disabled_user(tenant, disabled_at=OLD)
    u2 = _seed_disabled_user(tenant, disabled_at=OLD)
    fresh = _seed_disabled_user(tenant, disabled_at=FRESH)

    counts = await _purge(tenant, execute=True)
    assert counts["staff_users"] == 2

    with _mig() as conn, conn.cursor() as cur:
        cur.execute("SELECT external_idp_subject, email FROM users WHERE id IN (%s,%s)", (str(u1), str(u2)))
        rows = cur.fetchall()
        subs = {r[0] for r in rows}
        assert len(subs) == 2 and all(s.startswith("purged-") for s in subs)  # per-row unique
        cur.execute("SELECT display_name FROM users WHERE id=%s", (str(fresh),))
        assert cur.fetchone()[0] == "Real Name"  # fresh untouched


async def test_expired_outbox_and_cv_deleted_fresh_kept(tenant) -> None:
    old_ob, fresh_ob = _seed_outbox(tenant, created_at=OLD), _seed_outbox(tenant, created_at=FRESH)
    old_cv, fresh_cv = _seed_cv(tenant, created_at=OLD), _seed_cv(tenant, created_at=FRESH)

    await _purge(tenant, execute=True)
    assert not _exists("outbox_messages", old_ob) and _exists("outbox_messages", fresh_ob)
    assert not _exists("portal_contact_verifications", old_cv) and _exists("portal_contact_verifications", fresh_cv)


async def test_structural_tenant_isolation(tenant) -> None:
    other = insert_tenant("Globex", f"globex-{uuid.uuid4().hex[:8]}")
    mine = _seed_visit(tenant, status="Denied", created_at=OLD, decided_at=OLD)
    theirs = _seed_visit(other, status="Denied", created_at=OLD, decided_at=OLD)

    await _purge(tenant, execute=True)  # GUC = tenant only
    assert _visit_row(mine)[0] == "[redacted]"
    assert _visit_row(theirs)[0] == "Jane Real"  # other tenant untouched by RLS+GUC


async def test_idempotent_second_run(tenant) -> None:
    _seed_visit(tenant, status="Denied", created_at=OLD, decided_at=OLD)
    _seed_disabled_user(tenant, disabled_at=OLD)
    first = await _purge(tenant, execute=True)
    assert first["visits"] == 1 and first["staff_users"] == 1
    second = await _purge(tenant, execute=True)
    assert second["visits"] == 0 and second["staff_users"] == 0  # purged_at excludes them


async def test_dry_run_mutates_nothing(tenant) -> None:
    vid = _seed_visit(tenant, status="Denied", created_at=OLD, decided_at=OLD)
    counts = await _purge(tenant, execute=False)
    assert counts["visits"] == 1  # reports the count...
    assert _visit_row(vid)[0] == "Jane Real"  # ...but changed nothing
    # ...and wrote no audit
    async with TestPurgeSessionLocal() as s:
        await set_tenant_context(s, tenant)
        n = (await s.execute(select(AuditEvent).where(AuditEvent.tenant_id == tenant, AuditEvent.event_type == "retention.purge"))).scalars().all()
        assert n == []


async def test_purge_writes_pii_free_audit_with_counts(tenant) -> None:
    _seed_visit(tenant, status="Denied", created_at=OLD, decided_at=OLD)
    await _purge(tenant, execute=True)
    async with TestPurgeSessionLocal() as s:
        await set_tenant_context(s, tenant)
        ev = (await s.execute(select(AuditEvent).where(AuditEvent.tenant_id == tenant, AuditEvent.event_type == "retention.purge"))).scalar_one()
    assert ev.target_type == "tenant" and ev.target_id == tenant
    assert ev.details["counts"]["visits"] == 1
    # no PII anywhere in the audit row
    blob = f"{ev.actor}{ev.reason}{ev.details}"
    assert "jane@real.example" not in blob and "Jane Real" not in blob
