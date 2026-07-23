"""Task 3 (US-10): migration mechanics for 0001_tenancy_identity.

Runs against a fully disposable scratch database (created/dropped per test)
rather than the shared vms_test database, so this test's downgrade/upgrade
cycling never interferes with data other test modules create in vms_test.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from alembic import command

from app.db.provision_roles import provision_roles
from app.models.tenant import PLATFORM_TENANT_ID
from tests.conftest import SUPERUSER_MAINTENANCE_DSN, alembic_config

EXPECTED_TABLES = {
    "tenants",
    "roles",
    "permissions",
    "users",
    "role_permissions",
    "user_roles",
    "audit_events",
}


def _admin_dsn(db_name: str) -> str:
    return f"postgresql://vms:dev-only-not-for-real-secrets@localhost:5432/{db_name}"


def _migrator_dsn(db_name: str) -> str:
    return f"postgresql://vms_migrator:dev-only-not-for-real-secrets@localhost:5432/{db_name}"


@pytest.fixture()
def scratch_database():
    db_name = f"vms_migration_test_{uuid.uuid4().hex[:12]}"
    admin_conn = psycopg2.connect(SUPERUSER_MAINTENANCE_DSN)
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}"')
    provision_roles(_admin_dsn(db_name))
    try:
        yield db_name
    finally:
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        admin_conn.close()


def _table_names(db_name: str) -> set[str]:
    conn = psycopg2.connect(_admin_dsn(db_name))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def test_upgrade_head_creates_expected_tables(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    assert EXPECTED_TABLES <= _table_names(scratch_database)


def test_downgrade_then_upgrade_is_clean(scratch_database: str) -> None:
    """Full teardown (head -> base) must remove every 0001 table. Since
    US-11's 0002_visits_and_outbox is now also on this chain, "-1" from head
    only reverses 0002 (see tests/test_migration_0002.py for that
    incremental case) -- this test's own intent is "downgrading all the way
    is clean", so it now targets "base" explicitly rather than relying on
    "-1" meaning "the only migration", an assumption that stopped holding
    once a second migration was added."""
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")

    command.downgrade(cfg, "base")
    tables_after_downgrade = _table_names(scratch_database)
    assert not (EXPECTED_TABLES & tables_after_downgrade)

    command.upgrade(cfg, "head")
    assert EXPECTED_TABLES <= _table_names(scratch_database)


def test_reupgrade_at_head_is_idempotent(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # documented no-op re-run
    assert EXPECTED_TABLES <= _table_names(scratch_database)


def test_seed_data_present_after_upgrade(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")

    conn = psycopg2.connect(_admin_dsn(scratch_database))
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM roles ORDER BY code")
            role_codes = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT code FROM permissions ORDER BY code")
            permission_codes = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT 1 FROM tenants WHERE id = %s", (str(PLATFORM_TENANT_ID),))
            platform_row = cur.fetchone()
    finally:
        conn.close()

    assert role_codes == {"tenant_admin", "host", "reception_security", "dashboard_viewer"}
    assert "approve_deny_holds" in permission_codes  # visit-lifecycle.yaml compatibility
    assert platform_row is not None


def test_rls_enabled_and_forced_on_tenant_scoped_tables_only(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")

    conn = psycopg2.connect(_admin_dsn(scratch_database))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = ANY(%s)",
                (list(EXPECTED_TABLES),),
            )
            rows = dict((r[0], (r[1], r[2])) for r in cur.fetchall())
    finally:
        conn.close()

    for table in ("users", "user_roles", "audit_events"):
        assert rows[table] == (True, True), f"{table} must ENABLE+FORCE RLS"
    for table in ("tenants", "roles", "permissions", "role_permissions"):
        assert rows[table] == (False, False), f"{table} is tenant-global, no RLS expected"
