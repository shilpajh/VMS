"""Independent QA verification pass for US-07 (docs/plans/US-07.md).

These tests were written by qa-automation-engineer as an independent
verification pass over the existing US-07 test suite (test_retention_purge.py,
test_retention_erasure.py, ...). They target four specific coverage gaps
identified against the plan's Definition of Done that the existing tests
either did not fully prove or proved only partially:

1. ALL SIX visit PII columns (visitor_full_name, contact_value, host_hint,
   purpose, denial_reason, checkin_code_hash) scrubbed -- not just the three
   the existing tests happened to assert -- after BOTH purge and erasure.
2. "Fresh rows byte-identical after --execute", per store -- the existing
   tests spot-check one or two columns; this compares the FULL row tuple
   (every column) before vs after, for all four stores.
3. Crash-mid-run-then-rerun idempotency -- the existing test only reruns
   purge_tenant after a full prior run. This simulates a crash that scrubbed
   SOME rows before dying (by stamping purged_at directly, out from under
   purge_tenant) and proves a rerun touches exactly the remaining rows and
   does not re-mutate/double-count the already-purged one.
4. The 72h right-to-erasure SLA -- proves erasure is synchronous (completes
   inside the single DB transaction the caller already holds, not queued to
   the outbox/a worker) and measures wall-clock time for a representative
   call, so the "≤72h by completing in seconds" DoD claim is an actual
   measurement, not an assertion of intent.
5. `users.disabled_at` is actually stamped by the real disable path and
   cleared by the real re-enable path via the HTTP API -- the existing
   test_disabled_at_and_audit_details.py's docstring claims this is "covered
   end-to-end in test_api_identity.py's status tests", but neither file
   actually asserts `disabled_at` at the DB level; test_api_identity.py only
   checks the response body's `status` field. This is the exact reference
   timestamp the whole `staff_users` purge category depends on (ADR-005 §3),
   so an unverified claim here is a real gap, not a nitpick.

Synthetic data only (AGENTS.md). Follows the existing file conventions:
psycopg2 direct seeding via MIGRATOR_DSN, TestPurgeSessionLocal for the
NOBYPASSRLS vms_purge role.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.dependencies import get_token_validator
from app.auth.entra import EntraTokenValidator, StaticJWKSProvider
from app.crypto.hmac_hash import LocalHmacKeyProvider
from app.db.session import get_session
from app.domain.retention.erasure import erase_visitor
from app.domain.retention.purge import purge_tenant
from app.main import app
from app.models import AuditEvent, OutboxMessage
from tests.conftest import (
    MIGRATOR_DSN,
    TestAppSessionLocal,
    TestPurgeSessionLocal,
    assign_role,
    insert_tenant,
    insert_user,
    set_tenant_context,
)
from tests.support.entra_tokens import make_synthetic_idp

AUDIENCE = "api://smart-vms-core-api-dev-placeholder"

NOW = datetime.now(timezone.utc)
OLD = NOW - timedelta(days=200)   # expired for every window
FRESH = NOW - timedelta(hours=1)  # fresh for every window

HMAC = LocalHmacKeyProvider(b"coverage-gap-test-key-not-a-real-secret")


def _mig():
    conn = psycopg2.connect(MIGRATOR_DSN)
    conn.autocommit = True
    return conn


# --- full-row helpers (ALL columns, not a hand-picked subset) ---

_VISIT_COLUMNS = (
    "visitor_full_name, contact_channel, contact_value, host_hint, "
    "tracking_reference, checkin_code_hash, denial_reason, purpose, "
    "group_type, expected_group_size, status, correlation_id, "
    "privacy_notice_version, purged_at"
)
_USER_COLUMNS = "external_idp_subject, email, display_name, status, disabled_at, purged_at"
_OUTBOX_COLUMNS = "message_type, aggregate_type, aggregate_id, payload, status"
_CV_COLUMNS = "contact_channel, contact_value, otp_hash, privacy_notice_version"


def _row(table: str, columns: str, rid) -> tuple:
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {columns} FROM {table} WHERE id=%s", (str(rid),))
        row = cur.fetchone()
    assert row is not None, f"{table} row {rid} vanished (should still exist -- fresh/untouched)"
    return row


def _visit_full_row(vid):
    return _row("visits", _VISIT_COLUMNS, vid)


def _user_full_row(uid):
    return _row("users", _USER_COLUMNS, uid)


def _outbox_full_row(oid):
    return _row("outbox_messages", _OUTBOX_COLUMNS, oid)


def _cv_full_row(cid):
    return _row("portal_contact_verifications", _CV_COLUMNS, cid)


def _seed_visit(tenant_id, *, status, created_at, decided_at=None, with_optional_pii=True) -> uuid.UUID:
    vid = uuid.uuid4()
    host_hint = "Rahul Real" if with_optional_pii else None
    purpose = "Legal meeting re: confidential matter X" if with_optional_pii else None
    denial_reason = "Did not match watchlist policy Y" if with_optional_pii else None
    checkin_hash = "a" * 64 if with_optional_pii else None
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO visits (id, tenant_id, status, visitor_full_name, contact_channel, "
            "contact_value, host_hint, purpose, tracking_reference, denial_reason, "
            "checkin_code_hash, privacy_notice_version, correlation_id, created_at, decided_at) "
            "VALUES (%s,%s,%s,'Jane Real','email','jane@real.example',%s,%s,"
            "%s,%s,%s,'v1',%s,%s,%s)",
            (
                str(vid), str(tenant_id), status, host_hint, purpose,
                f"REQ-{uuid.uuid4().int % 10**12:012d}", denial_reason, checkin_hash,
                str(uuid.uuid4()), created_at, decided_at,
            ),
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


async def _purge(tenant_id, *, execute):
    async with TestPurgeSessionLocal() as s:
        await set_tenant_context(s, tenant_id)
        counts = await purge_tenant(s, tenant_id, execute=execute)
        await s.commit()
        return counts


@pytest.fixture()
def tenant():
    return insert_tenant("Acme", f"acme-{uuid.uuid4().hex[:8]}")


# ---------------------------------------------------------------------------
# Gap 1: ALL SIX visit PII columns scrubbed (not just 3), purge AND erasure.
# ---------------------------------------------------------------------------

async def test_purge_scrubs_all_six_visit_pii_columns(tenant) -> None:
    vid = _seed_visit(tenant, status="Denied", created_at=OLD, decided_at=OLD, with_optional_pii=True)

    await _purge(tenant, execute=True)

    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT visitor_full_name, contact_value, host_hint, purpose, "
            "denial_reason, checkin_code_hash, purged_at FROM visits WHERE id=%s",
            (str(vid),),
        )
        name, contact, host_hint, purpose, denial_reason, checkin_hash, purged_at = cur.fetchone()

    assert name == "[redacted]", "visitor_full_name not scrubbed"
    assert contact == "[redacted]", "contact_value not scrubbed"
    assert host_hint is None, "host_hint not scrubbed -- coverage gap"
    assert purpose is None, "purpose not scrubbed"
    assert denial_reason is None, "denial_reason not scrubbed -- coverage gap"
    assert checkin_hash is None, "checkin_code_hash not scrubbed -- coverage gap"
    assert purged_at is not None


async def test_erasure_scrubs_all_six_visit_pii_columns(tenant) -> None:
    vid = _seed_visit(tenant, status="Denied", created_at=OLD, decided_at=OLD, with_optional_pii=True)

    async with TestPurgeSessionLocal() as s:
        await set_tenant_context(s, tenant)
        await erase_visitor(
            s, tenant, contact_channel="email", contact_value="jane@real.example",
            hmac_provider=HMAC, execute=True,
        )
        await s.commit()

    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT visitor_full_name, contact_value, host_hint, purpose, "
            "denial_reason, checkin_code_hash, purged_at FROM visits WHERE id=%s",
            (str(vid),),
        )
        name, contact, host_hint, purpose, denial_reason, checkin_hash, purged_at = cur.fetchone()

    assert name == "[redacted]"
    assert contact == "[redacted]"
    assert host_hint is None, "erasure: host_hint not scrubbed -- coverage gap"
    assert purpose is None, "erasure: purpose not scrubbed"
    assert denial_reason is None, "erasure: denial_reason not scrubbed -- coverage gap"
    assert checkin_hash is None, "erasure: checkin_code_hash not scrubbed -- coverage gap"
    assert purged_at is not None


# ---------------------------------------------------------------------------
# Gap 2: fresh rows byte-identical after --execute, per store (full row,
# every column -- not a hand-picked subset).
# ---------------------------------------------------------------------------

async def test_fresh_rows_byte_identical_after_execute_all_stores(tenant) -> None:
    fresh_visit = _seed_visit(tenant, status="Denied", created_at=FRESH, decided_at=FRESH, with_optional_pii=True)
    fresh_user = _seed_disabled_user(tenant, disabled_at=FRESH)
    fresh_outbox = _seed_outbox(tenant, created_at=FRESH)
    fresh_cv = _seed_cv(tenant, created_at=FRESH)

    # Also seed an EXPIRED row of each kind so the purge actually does work
    # in this tenant (a no-op purge trivially leaves everything alone --
    # that would not prove anything about the fresh-row guarantee).
    _seed_visit(tenant, status="Denied", created_at=OLD, decided_at=OLD)
    _seed_disabled_user(tenant, disabled_at=OLD)
    _seed_outbox(tenant, created_at=OLD)
    _seed_cv(tenant, created_at=OLD)

    before = (
        _visit_full_row(fresh_visit),
        _user_full_row(fresh_user),
        _outbox_full_row(fresh_outbox),
        _cv_full_row(fresh_cv),
    )

    counts = await _purge(tenant, execute=True)
    # sanity: the purge actually did something in this tenant.
    assert counts["visits"] >= 1 and counts["staff_users"] >= 1
    assert counts["outbox_messages"] >= 1 and counts["contact_verifications"] >= 1

    after = (
        _visit_full_row(fresh_visit),
        _user_full_row(fresh_user),
        _outbox_full_row(fresh_outbox),
        _cv_full_row(fresh_cv),
    )

    assert before[0] == after[0], "fresh visits row mutated by purge"
    assert before[1] == after[1], "fresh users row mutated by purge"
    assert before[2] == after[2], "fresh outbox_messages row mutated by purge"
    assert before[3] == after[3], "fresh portal_contact_verifications row mutated by purge"


# ---------------------------------------------------------------------------
# Gap 3: crash-mid-run-then-rerun -- a rerun after a PARTIAL prior scrub (not
# just a full prior run) touches exactly the remaining rows, does not
# re-mutate/double-count the row a "crashed" run already finished, and the
# fresh row is still untouched throughout.
# ---------------------------------------------------------------------------

async def test_crash_mid_run_then_rerun_touches_only_remaining_rows(tenant) -> None:
    expired_a = _seed_visit(tenant, status="Denied", created_at=OLD, decided_at=OLD)
    expired_b = _seed_visit(tenant, status="Denied", created_at=OLD, decided_at=OLD)
    expired_c = _seed_visit(tenant, status="Requested", created_at=OLD)
    fresh = _seed_visit(tenant, status="Denied", created_at=FRESH, decided_at=FRESH)
    disabled_a = _seed_disabled_user(tenant, disabled_at=OLD)
    disabled_b = _seed_disabled_user(tenant, disabled_at=OLD)

    # Simulate: a prior purge_expired run scrubbed expired_a and disabled_a
    # then CRASHED (process killed / connection dropped) before it reached
    # expired_b, expired_c, disabled_b or wrote its audit event. This is done
    # via a DIRECT UPDATE (as vms_migrator), bypassing purge_tenant entirely,
    # to model an out-of-band partial mutation rather than merely calling
    # purge_tenant twice (which the existing idempotency test already covers).
    crash_ts = OLD + timedelta(seconds=1)
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE visits SET visitor_full_name='[redacted]', contact_value='[redacted]', "
            "host_hint=NULL, purpose=NULL, denial_reason=NULL, checkin_code_hash=NULL, "
            "purged_at=%s WHERE id=%s",
            (crash_ts, str(expired_a)),
        )
        cur.execute(
            "UPDATE users SET email='[redacted]@redacted.invalid', display_name='[redacted]', "
            "external_idp_subject=%s, purged_at=%s WHERE id=%s",
            (f"purged-{disabled_a}", crash_ts, str(disabled_a)),
        )
        # No audit event written for this partial "crashed" work -- exactly
        # what a real mid-run crash would leave behind.

    # The crash-simulated rows, BEFORE rerun:
    crashed_visit_before = _visit_full_row(expired_a)
    crashed_user_before = _user_full_row(disabled_a)

    # Rerun the (real) purge -- this is the resumed run after the "restart".
    resumed_counts = await _purge(tenant, execute=True)

    # Only the rows the crash did NOT reach are counted/touched this time.
    assert resumed_counts["visits"] == 2, (
        f"expected exactly the 2 not-yet-purged visits (expired_b, expired_c), "
        f"got {resumed_counts['visits']} -- crash-resume touched 0 additional rows failed"
    )
    assert resumed_counts["staff_users"] == 1, (
        f"expected exactly the 1 not-yet-purged user (disabled_b), got {resumed_counts['staff_users']}"
    )

    # The already-"crashed"-scrubbed rows are BYTE-IDENTICAL after the rerun
    # -- the rerun does not re-touch/re-mutate them (purged_at IS NULL excludes).
    assert _visit_full_row(expired_a) == crashed_visit_before, (
        "rerun re-mutated a row the crashed run had already scrubbed"
    )
    assert _user_full_row(disabled_a) == crashed_user_before, (
        "rerun re-mutated a user row the crashed run had already scrubbed"
    )

    # The rows the crash never reached are now scrubbed by the resumed run.
    for vid in (expired_b, expired_c):
        with _mig() as conn, conn.cursor() as cur:
            cur.execute("SELECT visitor_full_name, purged_at FROM visits WHERE id=%s", (str(vid),))
            name, purged_at = cur.fetchone()
        assert name == "[redacted]" and purged_at is not None

    with _mig() as conn, conn.cursor() as cur:
        cur.execute("SELECT display_name, purged_at FROM users WHERE id=%s", (str(disabled_b),))
        name, purged_at = cur.fetchone()
    assert name == "[redacted]" and purged_at is not None

    # Fresh row untouched throughout the whole crash+resume sequence.
    assert _visit_full_row(fresh)[0] == "Jane Real"

    # Exactly ONE audit event was written for the resumed run (the crashed
    # partial work wrote none) -- no duplicate/inflated counts across the
    # crash+resume sequence.
    async with TestPurgeSessionLocal() as s:
        await set_tenant_context(s, tenant)
        events = (
            await s.execute(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant, AuditEvent.event_type == "retention.purge"
                )
            )
        ).scalars().all()
    assert len(events) == 1, f"expected exactly 1 purge audit event across crash+resume, got {len(events)}"
    assert events[0].details["counts"]["visits"] == 2, (
        "the resumed run's audited count must reflect only what IT purged (2), "
        "not double-count the crash's earlier work"
    )

    # A THIRD run (fully idempotent from here) touches 0 additional rows.
    third_counts = await _purge(tenant, execute=True)
    assert third_counts == {
        "staff_users": 0, "visits": 0, "outbox_messages": 0, "contact_verifications": 0,
    }


# ---------------------------------------------------------------------------
# Gap 4: 72h erasure SLA -- erasure is synchronous (single transaction, not
# queued), and completes in a small fraction of a second for a representative
# subject. This is the actual measurement backing the plan's "satisfying
# <=72h by completing in seconds" claim.
# ---------------------------------------------------------------------------

async def test_erasure_completes_synchronously_within_one_transaction(tenant) -> None:
    """erase_visitor must not enqueue work (no outbox row for itself) --
    the erasure is complete when the call returns, not "eventually" via a
    worker. Also measures wall-clock elapsed time as evidence for the plan's
    72h-SLA claim ("completing in seconds")."""
    vid = _seed_visit(tenant, status="Denied", created_at=OLD, decided_at=OLD)
    _seed_cv(tenant, created_at=OLD)
    _seed_outbox(tenant, created_at=OLD)

    outbox_count_before = _count("outbox_messages")

    start = time.perf_counter()
    async with TestPurgeSessionLocal() as s:
        await set_tenant_context(s, tenant)
        counts = await erase_visitor(
            s, tenant, contact_channel="email", contact_value="jane@real.example",
            hmac_provider=HMAC, execute=True,
        )
        await s.commit()  # the erasure is durable/complete at THIS point --
                           # no further async step is required.
    elapsed_seconds = time.perf_counter() - start

    # Evidence: actual measured wall-clock time (never rounded toward
    # passing). This is orders of magnitude under the 72-hour SLA and
    # consistent with "completing in seconds", not queued/deferred.
    assert elapsed_seconds < 5.0, (
        f"erase_visitor took {elapsed_seconds:.4f}s in-process against local vms_test; "
        f"expected well under the 72h SLA / 'seconds' claim"
    )

    with _mig() as conn, conn.cursor() as cur:
        cur.execute("SELECT visitor_full_name, purged_at FROM visits WHERE id=%s", (str(vid),))
        name, purged_at = cur.fetchone()
    # Effect visible immediately after commit -- no polling/eventual step.
    assert name == "[redacted]" and purged_at is not None

    # No NEW outbox row was created to defer/queue the erasure itself (the
    # erasure DELETES existing anchored outbox rows; it never enqueues a
    # command for later execution the way a physical/device action would).
    assert _count("outbox_messages") <= outbox_count_before

    print(f"[US-07 evidence] erase_visitor wall-clock: {elapsed_seconds:.4f}s (SLA: <=72h)")


def _count(table: str) -> int:
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Gap 5: users.disabled_at is genuinely stamped by the real HTTP disable path
# and cleared by the real re-enable path -- exercised end-to-end via the
# same TestClient pattern as test_api_identity.py (this is the reference
# timestamp the whole staff_users purge category depends on, ADR-005 §3).
# ---------------------------------------------------------------------------

async def _override_get_session():
    async with TestAppSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture()
def idp():
    return make_synthetic_idp()


@pytest.fixture(autouse=True)
def _override_identity_dependencies(idp, _migrated_schema):
    provider = StaticJWKSProvider({idp.kid: idp.public_key_pem})
    validator = EntraTokenValidator(jwks_provider=provider, audience=AUDIENCE)
    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_token_validator] = lambda: validator
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    return TestClient(app)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _users_disabled_at(user_id) -> object:
    with _mig() as conn, conn.cursor() as cur:
        cur.execute("SELECT disabled_at FROM users WHERE id=%s", (str(user_id),))
        return cur.fetchone()[0]


def test_disable_via_api_stamps_disabled_at_and_reenable_clears_it(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    admin_oid = f"oid-admin-{uuid.uuid4().hex[:8]}"
    admin_user_id = insert_user(tenant_id, admin_oid)
    assign_role(tenant_id, admin_user_id, "tenant_admin")

    target_oid = f"oid-target-{uuid.uuid4().hex[:8]}"
    target_user_id = insert_user(tenant_id, target_oid)
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=admin_oid)

    # baseline: freshly-created active user has no disabled_at.
    assert _users_disabled_at(target_user_id) is None

    disable_resp = client.patch(
        f"/tenants/{tenant_id}/users/{target_user_id}",
        headers=_headers(token),
        json={"status": "disabled", "reason": "left the company"},
    )
    assert disable_resp.status_code == 200
    disabled_at = _users_disabled_at(target_user_id)
    assert disabled_at is not None, (
        "GAP: PATCH .../users/{id} with status=disabled did not stamp "
        "users.disabled_at -- the staff_users retention clock (ADR-005 Sec 3) "
        "would never advance for this user"
    )

    reenable_resp = client.patch(
        f"/tenants/{tenant_id}/users/{target_user_id}",
        headers=_headers(token),
        json={"status": "active", "reason": "rejoined"},
    )
    assert reenable_resp.status_code == 200
    assert _users_disabled_at(target_user_id) is None, (
        "GAP: re-enabling a user did not clear users.disabled_at -- a "
        "re-enabled (active) user would still look expired to the purge "
        "on a stale clock"
    )


# ---------------------------------------------------------------------------
# Gap 6 (BUG, not a coverage gap): the US-07 DoD states verbatim "No
# secrets/PII in logs or in audit `details`." erase_subject.py's stdout
# output includes the raw --value the operator passed (e.g. a real email/
# phone in a real invocation), on BOTH the dry-run report and the applied
# confirmation -- i.e. every single invocation, not just the audit DB row.
# The audit row itself correctly uses a keyed HMAC (SP-B1, proven by
# test_retention_erasure.py::test_erasure_audit_is_pii_free_keyed_hmac);
# this test proves the *console output* the DoD bullet also covers does not
# meet the same bar. This is scripts/erase_subject.py application code
# (out of scope for a QA agent to edit); reported here as a real,
# demonstrated bug, not fixed.
# ---------------------------------------------------------------------------

from scripts import erase_subject as _erase_subject_script  # noqa: E402


def test_erase_subject_cli_output_contains_no_raw_contact_pii(tenant, monkeypatch, capsys) -> None:
    monkeypatch.setattr(_erase_subject_script, "PurgeSessionLocal", TestPurgeSessionLocal)
    monkeypatch.setattr(_erase_subject_script, "resolve_tenant_id", lambda slug, _t=tenant: _t)

    rc = _erase_subject_script.main(
        ["--tenant", "acme-demo", "--channel", "email", "--value", "jane@real.example"]
    )
    assert rc == 0
    dry_run_out = capsys.readouterr().out
    assert "jane@real.example" not in dry_run_out, (
        "BUG: erase_subject.py's dry-run stdout contains the raw contact "
        f"value verbatim -- DoD requires 'No secrets/PII in logs'. Output was:\n{dry_run_out!r}"
    )
