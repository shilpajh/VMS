"""Task 1 (US-13a): migration mechanics for 0004_portal_contact_verification,
against a disposable scratch database (mirrors test_migration_0003.py).
Confirms: the new `portal_contact_verifications` table lands with RLS
enable+force and both indexes; the five new `visits` columns land nullable;
a -1 downgrade removes exactly this migration's additions with 0003's
intact.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from alembic import command

from app.db.provision_roles import provision_roles
from tests.conftest import SUPERUSER_MAINTENANCE_DSN, alembic_config

NEW_TABLE = "portal_contact_verifications"
NEW_VISITS_COLUMNS = {
    "purpose",
    "group_type",
    "expected_group_size",
    "identity_verification_choice",
    "contact_verified",
}


def _admin_dsn(db_name: str) -> str:
    return f"postgresql://vms:dev-only-not-for-real-secrets@localhost:5432/{db_name}"


def _migrator_dsn(db_name: str) -> str:
    return f"postgresql://vms_migrator:dev-only-not-for-real-secrets@localhost:5432/{db_name}"


@pytest.fixture()
def scratch_database():
    db_name = f"vms_migration_0004_test_{uuid.uuid4().hex[:12]}"
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


def test_upgrade_head_creates_table_and_columns(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    assert NEW_TABLE in _table_names(scratch_database)
    assert NEW_VISITS_COLUMNS <= _visits_columns(scratch_database)


def test_new_table_has_rls_enabled_and_forced(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    conn = psycopg2.connect(_admin_dsn(scratch_database))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                (NEW_TABLE,),
            )
            rowsec, forced = cur.fetchone()
    finally:
        conn.close()
    assert rowsec is True
    assert forced is True


def test_new_table_has_both_expected_indexes(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    conn = psycopg2.connect(_admin_dsn(scratch_database))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE tablename = %s", (NEW_TABLE,)
            )
            defs = " ".join(row[0] for row in cur.fetchall())
    finally:
        conn.close()
    # tuple-lookup index (verify/supersede path) and token-lookup index (submission path)
    assert "contact_value" in defs
    assert "verification_token_hash" in defs


def test_new_visits_data_columns_nullable_and_flag_notnull_with_default(scratch_database: str) -> None:
    """The four visitor-supplied data columns are nullable (existing visits
    predate them, no backfill). `contact_verified` is NOT NULL with a
    server_default 'false' -- safe on existing rows (Postgres fills the
    default) and correct as a never-null trust flag, mirroring
    visits.privacy_notice_acknowledged's treatment."""
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    conn = psycopg2.connect(_admin_dsn(scratch_database))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'visits' AND column_name = ANY(%s)",
                (list(NEW_VISITS_COLUMNS),),
            )
            rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    finally:
        conn.close()
    nullable_data = {"purpose", "group_type", "expected_group_size", "identity_verification_choice"}
    for col in nullable_data:
        assert rows[col][0] == "YES", f"{col} should be nullable"
    assert rows["contact_verified"][0] == "NO"
    assert "false" in (rows["contact_verified"][1] or "").lower()


def test_downgrade_one_step_removes_only_0004_additions(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    assert NEW_TABLE not in _table_names(scratch_database)
    cols = _visits_columns(scratch_database)
    assert not (NEW_VISITS_COLUMNS & cols)
    assert "checked_in_at" in cols, "0003's visits columns must survive a -1 downgrade"


def test_reupgrade_after_downgrade_is_clean(scratch_database: str) -> None:
    cfg = alembic_config(_migrator_dsn(scratch_database))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
    assert NEW_TABLE in _table_names(scratch_database)
