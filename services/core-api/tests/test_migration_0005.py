"""Task 1 (US-07): migration mechanics for 0005_retention, against a
disposable scratch database (mirrors test_migration_0004.py). Confirms the
retention_policies table + audit_events.details + users.disabled_at/purged_at
+ visits.purged_at land at upgrade with RLS/index/unique, and a -1 downgrade
removes exactly this migration's additions.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from alembic import command

from app.db.provision_roles import provision_roles
from tests.conftest import SUPERUSER_MAINTENANCE_DSN, alembic_config

NEW_TABLE = "retention_policies"


def _admin_dsn(db_name: str) -> str:
    return f"postgresql://vms:dev-only-not-for-real-secrets@localhost:5432/{db_name}"


def _migrator_dsn(db_name: str) -> str:
    return f"postgresql://vms_migrator:dev-only-not-for-real-secrets@localhost:5432/{db_name}"


@pytest.fixture()
def scratch_database():
    db_name = f"vms_migration_0005_test_{uuid.uuid4().hex[:12]}"
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


def _columns(db_name: str, table: str) -> set[str]:
    conn = psycopg2.connect(_admin_dsn(db_name))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
            )
            return {r[0] for r in cur.fetchall()}
    finally:
        conn.close()


def _tables(db_name: str) -> set[str]:
    conn = psycopg2.connect(_admin_dsn(db_name))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
            return {r[0] for r in cur.fetchall()}
    finally:
        conn.close()


def test_upgrade_head_adds_table_and_columns(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    assert NEW_TABLE in _tables(scratch_database)
    assert {"tenant_id", "data_category", "retention_seconds"} <= _columns(scratch_database, NEW_TABLE)
    assert "details" in _columns(scratch_database, "audit_events")
    assert {"disabled_at", "purged_at"} <= _columns(scratch_database, "users")
    assert "purged_at" in _columns(scratch_database, "visits")


def test_new_table_rls_and_unique(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    conn = psycopg2.connect(_admin_dsn(scratch_database))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname=%s",
                (NEW_TABLE,),
            )
            rowsec, forced = cur.fetchone()
            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE tablename=%s", (NEW_TABLE,)
            )
            defs = " ".join(r[0] for r in cur.fetchall())
    finally:
        conn.close()
    assert rowsec and forced
    assert "tenant_id" in defs  # tenant index
    assert "UNIQUE" in defs.upper() and "data_category" in defs  # unique(tenant, category)


def test_downgrade_one_step_removes_only_0005(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    assert NEW_TABLE not in _tables(scratch_database)
    audit_cols = _columns(scratch_database, "audit_events")
    assert "details" not in audit_cols
    assert "created_at" in audit_cols  # 0001's audit columns survive
    assert "disabled_at" not in _columns(scratch_database, "users")
    assert "purged_at" not in _columns(scratch_database, "visits")


def test_reupgrade_after_downgrade_clean(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
    assert NEW_TABLE in _tables(scratch_database)
