"""Task 6 (US-07): ops-script guards + wiring. Synthetic data only.

The activation guards (echoed slug, enabled flag, non-prod env) are the
human-gated-activation fence -- proven here to REFUSE by default and only act
under the full guard set. The DB-touching path is exercised against vms_test
by pointing the script's session factory at TestPurgeSessionLocal and stubbing
the tenant-slug lookup.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest

from app.config import settings
from scripts import erase_subject, purge_expired
from scripts._retention_guards import ActivationRefused, assert_execute_authorized
from tests.conftest import (
    MIGRATOR_DSN,
    TestPurgeSessionLocal,
    insert_tenant,
    set_tenant_context,
)

SLUG = "acme-demo"


def _mig():
    conn = psycopg2.connect(MIGRATOR_DSN)
    conn.autocommit = True
    return conn


def _seed_expired_denied(tenant_id) -> uuid.UUID:
    vid = uuid.uuid4()
    with _mig() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO visits (id, tenant_id, status, visitor_full_name, contact_channel, "
            "contact_value, tracking_reference, privacy_notice_version, correlation_id, "
            "created_at, decided_at) VALUES "
            "(%s,%s,'Denied','Jane Real','email','jane@real.example',%s,'v1',%s,"
            "now() - interval '200 days', now() - interval '200 days')",
            (str(vid), str(tenant_id), f"REQ-{uuid.uuid4().int % 10**12:012d}", str(uuid.uuid4())),
        )
    return vid


def _visit_name(vid):
    with _mig() as conn, conn.cursor() as cur:
        cur.execute("SELECT visitor_full_name FROM visits WHERE id=%s", (str(vid),))
        return cur.fetchone()[0]


@pytest.fixture()
def tenant():
    return insert_tenant("Acme", f"acme-{uuid.uuid4().hex[:8]}")


@pytest.fixture(autouse=True)
def _wire_scripts_to_test_db(tenant, monkeypatch):
    """Point both scripts' session factory + tenant resolver at vms_test."""
    for mod in (purge_expired, erase_subject):
        monkeypatch.setattr(mod, "PurgeSessionLocal", TestPurgeSessionLocal)
        monkeypatch.setattr(mod, "resolve_tenant_id", lambda slug, _t=tenant: _t)


# --- guard unit tests (no DB) ---

def test_execute_refused_without_matching_confirm():
    with pytest.raises(ActivationRefused, match="confirm-tenant"):
        assert_execute_authorized(tenant_slug=SLUG, confirm_tenant=None)
    with pytest.raises(ActivationRefused, match="confirm-tenant"):
        assert_execute_authorized(tenant_slug=SLUG, confirm_tenant="wrong")


def test_execute_refused_when_not_enabled(monkeypatch):
    monkeypatch.setattr(settings, "app_environment", "local")
    monkeypatch.setattr(settings, "retention_purge_enabled", False)
    with pytest.raises(ActivationRefused, match="not activated"):
        assert_execute_authorized(tenant_slug=SLUG, confirm_tenant=SLUG)


def test_execute_refused_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_environment", "production")
    monkeypatch.setattr(settings, "retention_purge_enabled", True)
    with pytest.raises(ActivationRefused, match="production"):
        assert_execute_authorized(tenant_slug=SLUG, confirm_tenant=SLUG)


def test_execute_authorized_under_full_guard_set(monkeypatch):
    monkeypatch.setattr(settings, "app_environment", "local")
    monkeypatch.setattr(settings, "retention_purge_enabled", True)
    assert_execute_authorized(tenant_slug=SLUG, confirm_tenant=SLUG)  # no raise


# --- purge_expired CLI ---

def test_purge_dry_run_default_mutates_nothing(tenant, capsys):
    vid = _seed_expired_denied(tenant)
    rc = purge_expired.main(["--tenant", SLUG])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "1 visits" in out
    assert _visit_name(vid) == "Jane Real"  # untouched


def test_purge_execute_requires_confirmation(tenant, monkeypatch):
    monkeypatch.setattr(settings, "retention_purge_enabled", True)
    with pytest.raises(SystemExit):  # argparse error -> SystemExit(2)
        purge_expired.main(["--tenant", SLUG, "--execute"])  # no --confirm-tenant


def test_purge_execute_applies_under_full_guards(tenant, monkeypatch, capsys):
    monkeypatch.setattr(settings, "app_environment", "local")
    monkeypatch.setattr(settings, "retention_purge_enabled", True)
    vid = _seed_expired_denied(tenant)
    rc = purge_expired.main(["--tenant", SLUG, "--execute", "--confirm-tenant", SLUG])
    assert rc == 0
    assert "APPLIED" in capsys.readouterr().out
    assert _visit_name(vid) == "[redacted]"  # scrubbed


# --- erase_subject CLI ---

def test_erase_requires_exactly_one_subject_kind(tenant):
    with pytest.raises(SystemExit):  # neither
        erase_subject.main(["--tenant", SLUG])
    with pytest.raises(SystemExit):  # both
        erase_subject.main(
            ["--tenant", SLUG, "--staff-email", "x@y.z", "--channel", "email", "--value", "a@b.c"]
        )


def test_erase_dry_run_default_mutates_nothing(tenant, capsys):
    vid = _seed_expired_denied(tenant)
    rc = erase_subject.main(["--tenant", SLUG, "--channel", "email", "--value", "jane@real.example"])
    assert rc == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert _visit_name(vid) == "Jane Real"  # untouched
