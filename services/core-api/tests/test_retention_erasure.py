"""Task 5 (US-07): right-to-erasure. Synthetic data only. Exercises erasure
as the NOBYPASSRLS `vms_purge` role with a per-tenant GUC, so structural
isolation (SP-B2) is what's actually tested. Covers the DA-B3 dual-anchor
outbox cascade (visit_id AND verification_id), the DA-B2 on-site refusal, and
the SP-B1 keyed-HMAC subject_ref (never a raw/reversible contact).
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from sqlalchemy import select

from app.crypto.hmac_hash import LocalHmacKeyProvider, hmac_hash
from app.domain.retention.erasure import (
    OnSiteErasureRefused,
    erase_staff,
    erase_visitor,
)
from app.models import AuditEvent
from tests.conftest import (
    MIGRATOR_DSN,
    TestPurgeSessionLocal,
    insert_tenant,
    set_tenant_context,
)

CHANNEL = "email"
CONTACT = "jane@real.example"
HMAC = LocalHmacKeyProvider(b"erasure-test-key-not-a-real-secret")


def _mig():
    conn = psycopg2.connect(MIGRATOR_DSN)
    conn.autocommit = True
    return conn


def _seed_visit(tenant_id, *, status="Denied", contact=CONTACT) -> uuid.UUID:
    vid = uuid.uuid4()
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO visits (id, tenant_id, status, visitor_full_name, contact_channel, "
            "contact_value, host_hint, purpose, tracking_reference, privacy_notice_version, "
            "correlation_id, created_at) "
            "VALUES (%s,%s,%s,'Jane Real','email',%s,'Rahul','Legal meeting',"
            "%s,'v1',%s, now())",
            (str(vid), str(tenant_id), status, contact,
             f"REQ-{uuid.uuid4().int % 10**12:012d}", str(uuid.uuid4())),
        )
    return vid


def _seed_cv(tenant_id, *, contact=CONTACT) -> uuid.UUID:
    cid = uuid.uuid4()
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO portal_contact_verifications (id, tenant_id, contact_channel, contact_value, "
            "otp_hash, otp_expires_at, privacy_notice_version, created_at) "
            "VALUES (%s,%s,'email',%s,'h', now() + interval '5 min','v1', now())",
            (str(cid), str(tenant_id), contact),
        )
    return cid


def _seed_outbox(tenant_id, *, aggregate_type, aggregate_id) -> uuid.UUID:
    oid = uuid.uuid4()
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO outbox_messages (id, tenant_id, message_type, aggregate_type, aggregate_id, "
            "correlation_id, idempotency_key, payload, payload_key_ref, status, created_at) "
            "VALUES (%s,%s,'x',%s,%s,%s,%s,'k','cipher','pending', now())",
            (str(oid), str(tenant_id), aggregate_type, str(aggregate_id),
             str(uuid.uuid4()), uuid.uuid4().hex),
        )
    return oid


def _visit_row(vid):
    with _mig() as conn, conn.cursor() as cur:
        cur.execute("SELECT visitor_full_name, contact_value, purpose, purged_at FROM visits WHERE id=%s", (str(vid),))
        return cur.fetchone()


def _user_row(uid):
    with _mig() as conn, conn.cursor() as cur:
        cur.execute("SELECT email, display_name, purged_at FROM users WHERE id=%s", (str(uid),))
        return cur.fetchone()


def _exists(table, rid):
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {table} WHERE id=%s", (str(rid),))
        return cur.fetchone() is not None


def _seed_disabled_user(tenant_id) -> uuid.UUID:
    uid = uuid.uuid4()
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, tenant_id, external_idp_subject, email, display_name, status) "
            "VALUES (%s,%s,%s,'staff@real.example','Real Name','disabled')",
            (str(uid), str(tenant_id), f"oid-{uuid.uuid4().hex[:8]}"),
        )
    return uid


async def _run(tenant_id, coro_factory):
    async with TestPurgeSessionLocal() as s:
        await set_tenant_context(s, tenant_id)
        result = await coro_factory(s)
        await s.commit()
        return result


@pytest.fixture()
def tenant():
    return insert_tenant("Acme", f"acme-{uuid.uuid4().hex[:8]}")


async def test_erase_visitor_cascades_both_outbox_anchors(tenant) -> None:
    vid = _seed_visit(tenant)
    cid = _seed_cv(tenant)
    ob_visit = _seed_outbox(tenant, aggregate_type="visit", aggregate_id=vid)
    ob_verif = _seed_outbox(tenant, aggregate_type="portal_contact_verification", aggregate_id=cid)

    counts = await _run(tenant, lambda s: erase_visitor(
        s, tenant, contact_channel=CHANNEL, contact_value=CONTACT, hmac_provider=HMAC, execute=True))

    assert counts == {"visits": 1, "contact_verifications": 1, "outbox_messages": 2}
    # visit scrubbed + marked
    name, contact, purpose, purged_at = _visit_row(vid)
    assert name == "[redacted]" and contact == "[redacted]" and purpose is None and purged_at is not None
    # cv + BOTH outbox anchors deleted (DA-B3)
    assert not _exists("portal_contact_verifications", cid)
    assert not _exists("outbox_messages", ob_visit)
    assert not _exists("outbox_messages", ob_verif)


async def test_erase_visitor_refuses_on_site(tenant) -> None:
    _seed_visit(tenant, status="CheckedIn")
    kept = _seed_visit(tenant, status="Denied")
    with pytest.raises(OnSiteErasureRefused):
        await _run(tenant, lambda s: erase_visitor(
            s, tenant, contact_channel=CHANNEL, contact_value=CONTACT, hmac_provider=HMAC, execute=True))
    # nothing scrubbed -- the refusal is total, not partial
    assert _visit_row(kept)[0] == "Jane Real"


async def test_erase_visitor_dry_run_mutates_nothing(tenant) -> None:
    vid = _seed_visit(tenant)
    cid = _seed_cv(tenant)
    counts = await _run(tenant, lambda s: erase_visitor(
        s, tenant, contact_channel=CHANNEL, contact_value=CONTACT, hmac_provider=HMAC, execute=False))
    assert counts == {"visits": 1, "contact_verifications": 1, "outbox_messages": 0}
    assert _visit_row(vid)[0] == "Jane Real"
    assert _exists("portal_contact_verifications", cid)


async def test_erase_staff_scrubs_user(tenant) -> None:
    uid = _seed_disabled_user(tenant)
    counts = await _run(tenant, lambda s: erase_staff(
        s, tenant, email="staff@real.example", hmac_provider=HMAC, execute=True))
    assert counts == {"staff_users": 1}
    email, display_name, purged_at = _user_row(uid)
    assert email == "[redacted]@redacted.invalid" and display_name == "[redacted]" and purged_at is not None


async def test_erase_visitor_structural_tenant_isolation(tenant) -> None:
    other = insert_tenant("Globex", f"globex-{uuid.uuid4().hex[:8]}")
    mine = _seed_visit(tenant)
    theirs = _seed_visit(other)  # same contact, different tenant

    await _run(tenant, lambda s: erase_visitor(
        s, tenant, contact_channel=CHANNEL, contact_value=CONTACT, hmac_provider=HMAC, execute=True))

    assert _visit_row(mine)[0] == "[redacted]"
    assert _visit_row(theirs)[0] == "Jane Real"  # other tenant untouched by RLS+GUC


async def test_erasure_audit_is_pii_free_keyed_hmac(tenant) -> None:
    _seed_visit(tenant)
    await _run(tenant, lambda s: erase_visitor(
        s, tenant, contact_channel=CHANNEL, contact_value=CONTACT, hmac_provider=HMAC, execute=True))

    async with TestPurgeSessionLocal() as s:
        await set_tenant_context(s, tenant)
        ev = (await s.execute(select(AuditEvent).where(
            AuditEvent.tenant_id == tenant, AuditEvent.event_type == "retention.erasure"))).scalar_one()

    assert ev.target_type == "tenant" and ev.target_id == tenant
    # subject_ref is the keyed HMAC -- reproducible only WITH the key, and it
    # is NOT the raw contact or a bare (keyless) digest.
    assert ev.details["subject_ref"] == hmac_hash(f"{CHANNEL}:{CONTACT}", HMAC)
    blob = f"{ev.actor}{ev.reason}{ev.details}"
    assert CONTACT not in blob and "Jane Real" not in blob
