"""Task 2 (US-11): migration mechanics for 0002_visits_and_outbox, against a
fully disposable scratch database (mirrors tests/test_migration.py's
pattern for 0001). Confirms: new tables + RLS + grants land at upgrade, and
downgrading exactly one step (-1) removes ONLY this migration's additions
(visits, outbox_messages, view_visits seed, tenants.public_slug) while
0001's tables remain intact -- proving 0002's own downgrade() is correct in
isolation, not just as part of a full teardown to base.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from alembic import command

from app.db.provision_roles import provision_roles
from tests.conftest import SUPERUSER_MAINTENANCE_DSN, alembic_config

NEW_TABLES = {"visits", "outbox_messages"}
PRE_EXISTING_0001_TABLES = {"tenants", "roles", "permissions", "users", "role_permissions", "user_roles", "audit_events"}


def _admin_dsn(db_name: str) -> str:
    return f"postgresql://vms:dev-only-not-for-real-secrets@localhost:5432/{db_name}"


def _migrator_dsn(db_name: str) -> str:
    return f"postgresql://vms_migrator:dev-only-not-for-real-secrets@localhost:5432/{db_name}"


@pytest.fixture()
def scratch_database():
    db_name = f"vms_migration_0002_test_{uuid.uuid4().hex[:12]}"
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


def _column_exists(db_name: str, table: str, column: str) -> bool:
    conn = psycopg2.connect(_admin_dsn(db_name))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s",
                (table, column),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def test_upgrade_head_creates_visits_and_outbox_tables(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    assert NEW_TABLES <= _table_names(scratch_database)
    assert _column_exists(scratch_database, "tenants", "public_slug")


def test_downgrade_one_step_removes_only_0002_additions(scratch_database: str) -> None:
    """Upgrades to 0002 specifically (not "head", which now includes
    0003_visit_checkin on top per US-01) -- a relative "-1 from head" would
    silently start testing the wrong migration's downgrade() every time a
    later migration lands, so this pins the absolute revision under test."""
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "0002_visits_and_outbox")

    command.downgrade(cfg, "-1")
    tables = _table_names(scratch_database)

    assert not (NEW_TABLES & tables), "0002's own tables must be gone after a -1 downgrade"
    assert PRE_EXISTING_0001_TABLES <= tables, "0001's tables must survive a -1 downgrade from head"
    assert not _column_exists(scratch_database, "tenants", "public_slug")


def test_reupgrade_after_downgrade_one_step_is_clean(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
    assert NEW_TABLES <= _table_names(scratch_database)


def test_view_visits_permission_seeded_at_head(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")

    conn = psycopg2.connect(_admin_dsn(scratch_database))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT r.code FROM role_permissions rp "
                "JOIN roles r ON r.id = rp.role_id "
                "JOIN permissions p ON p.id = rp.permission_id "
                "WHERE p.code = 'view_visits'"
            )
            granted_roles = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    assert granted_roles == {"reception_security", "tenant_admin"}


def test_rls_enabled_and_forced_on_visits_and_outbox(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")

    conn = psycopg2.connect(_admin_dsn(scratch_database))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = ANY(%s)",
                (list(NEW_TABLES),),
            )
            rows = dict((r[0], (r[1], r[2])) for r in cur.fetchall())
    finally:
        conn.close()

    for table in NEW_TABLES:
        assert rows[table] == (True, True), f"{table} must ENABLE+FORCE RLS"


def test_vms_app_grants_exclude_delete_on_visits_and_outbox(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")

    conn = psycopg2.connect(_admin_dsn(scratch_database))
    try:
        with conn.cursor() as cur:
            for table in NEW_TABLES:
                cur.execute(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_name = %s AND grantee = 'vms_app'",
                    (table,),
                )
                privileges = {row[0] for row in cur.fetchall()}
                assert privileges == {"SELECT", "INSERT", "UPDATE"}, (table, privileges)
    finally:
        conn.close()
