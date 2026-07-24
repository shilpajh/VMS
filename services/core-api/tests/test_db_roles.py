"""Task 1 (US-10): DB role provisioning.

Confirms the two non-superuser Postgres roles required by ADR-001 §1/N3
exist with the correct attributes:
  - vms_app: the request-path role, subject to RLS (NOBYPASSRLS).
  - vms_migrator: the migration/ops role, BYPASSRLS, used only off the
    request path (Alembic, scripts/bootstrap_tenant.py, future US-07 purge).

The full fail-closed-without-SET-LOCAL behavior is exercised once RLS policy
is in place, in tests/test_tenant_isolation.py (task 4). This file only
confirms roles/grants exist with the expected privileges, per the plan.
"""

from __future__ import annotations

import psycopg2
import psycopg2.errors
import pytest

from tests.conftest import APP_DSN, MIGRATOR_DSN, SUPERUSER_DSN


def _role_attrs(rolname: str) -> tuple[bool, bool, bool, bool, bool]:
    conn = psycopg2.connect(SUPERUSER_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin "
                "FROM pg_roles WHERE rolname = %s",
                (rolname,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None, f"role {rolname} does not exist"
    return row


def test_vms_app_role_is_non_superuser_and_not_bypassrls() -> None:
    rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin = _role_attrs("vms_app")
    assert rolsuper is False
    assert rolbypassrls is False
    assert rolcreatedb is False
    assert rolcreaterole is False
    assert rolcanlogin is True


def test_vms_migrator_role_is_bypassrls_and_non_superuser() -> None:
    rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin = _role_attrs("vms_migrator")
    assert rolsuper is False
    assert rolbypassrls is True
    assert rolcanlogin is True


def test_vms_app_can_connect_but_cannot_create_tables() -> None:
    """vms_app has no CREATE on schema public — it never issues DDL."""
    conn = psycopg2.connect(APP_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("CREATE TABLE _role_probe_app (id int)")
    finally:
        conn.close()


def test_vms_migrator_can_connect_and_create_tables() -> None:
    """vms_migrator has CREATE on schema public — it runs migrations."""
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS _role_probe_migrator (id int)")
            cur.execute("DROP TABLE _role_probe_migrator")
    finally:
        conn.close()
