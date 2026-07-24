"""Task 1 (US-01): migration mechanics for 0003_visit_checkin, against a
fully disposable scratch database (mirrors tests/test_migration_0002.py's
pattern). Confirms: the three new `visits` columns land at upgrade and are
removed cleanly by a -1 downgrade, with 0002's own tables/columns
untouched -- proving 0003's downgrade() is correct in isolation.

No RBAC seed/policy-version change in this migration (US-01 plan's Scope
amendment: `checkin_confirm` already exists from US-10's baseline) -- so,
unlike test_migration_0002.py, there is no permission-seed assertion here.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from alembic import command

from app.db.provision_roles import provision_roles
from tests.conftest import SUPERUSER_MAINTENANCE_DSN, alembic_config

NEW_VISITS_COLUMNS = {"checkin_code_expires_at", "checked_in_by_user_id", "checked_in_at"}


def _admin_dsn(db_name: str) -> str:
    return f"postgresql://vms:dev-only-not-for-real-secrets@localhost:5432/{db_name}"


def _migrator_dsn(db_name: str) -> str:
    return f"postgresql://vms_migrator:dev-only-not-for-real-secrets@localhost:5432/{db_name}"


@pytest.fixture()
def scratch_database():
    db_name = f"vms_migration_0003_test_{uuid.uuid4().hex[:12]}"
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


def _visits_columns(db_name: str) -> set[str]:
    conn = psycopg2.connect(_admin_dsn(db_name))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'visits'"
            )
            return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def test_upgrade_head_adds_the_three_new_visits_columns(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    assert NEW_VISITS_COLUMNS <= _visits_columns(scratch_database)


def test_downgrade_one_step_removes_only_0003_columns(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")

    command.downgrade(cfg, "-1")
    columns = _visits_columns(scratch_database)

    assert not (NEW_VISITS_COLUMNS & columns), "0003's own columns must be gone after a -1 downgrade"
    assert "checkin_code_hash" in columns, "0002's own visits columns must survive a -1 downgrade"


def test_reupgrade_after_downgrade_one_step_is_clean(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
    assert NEW_VISITS_COLUMNS <= _visits_columns(scratch_database)


def test_new_columns_are_all_nullable(scratch_database: str) -> None:
    """None of the three new columns can be NOT NULL -- every pre-existing
    Registered visit (created before this migration) lacks them, and a
    NOT NULL column would break on those rows with no backfill plan."""
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")

    conn = psycopg2.connect(_admin_dsn(scratch_database))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'visits' AND column_name = ANY(%s)",
                (list(NEW_VISITS_COLUMNS),),
            )
            nullability = dict(cur.fetchall())
    finally:
        conn.close()
    assert all(v == "YES" for v in nullability.values())
