"""Task 4 (US-10): RLS fail-closed tenant isolation, exercised directly at
the Postgres layer as the `vms_app` role (never vms_migrator/superuser,
which bypass RLS by design and would hide a broken policy).

Covers the Gherkin scenario "Cross-tenant isolation on user management" at
the DB layer, beneath whatever the application-level 403 check does (defense
in depth, ADR-001 §1).
"""

from __future__ import annotations

import uuid

import psycopg2
import psycopg2.errors
import pytest

from tests.conftest import APP_DSN, MIGRATOR_DSN


def _insert_tenant(name: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (id, name, entra_tenant_id, status) "
                "VALUES (%s, %s, %s, 'active')",
                (str(tenant_id), name, f"entra-tid-{tenant_id}"),
            )
    finally:
        conn.close()
    return tenant_id


def _insert_user(tenant_id: uuid.UUID, oid: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (id, tenant_id, external_idp_subject, email, display_name) "
                "VALUES (%s, %s, %s, %s, %s)",
                (str(user_id), str(tenant_id), oid, f"{oid}@example.com", oid),
            )
    finally:
        conn.close()
    return user_id


@pytest.fixture()
def two_tenants_with_users():
    tenant_a = _insert_tenant("Acme")
    tenant_b = _insert_tenant("Globex")
    user_a = _insert_user(tenant_a, f"oid-a-{uuid.uuid4().hex[:8]}")
    user_b = _insert_user(tenant_b, f"oid-b-{uuid.uuid4().hex[:8]}")
    return {"tenant_a": tenant_a, "tenant_b": tenant_b, "user_a": user_a, "user_b": user_b}


def test_query_without_set_local_raises_fail_closed(two_tenants_with_users) -> None:
    """No GUC set -> current_setting('app.current_tenant_id') (single-arg
    form) raises rather than silently returning all rows across tenants."""
    conn = psycopg2.connect(APP_DSN)
    try:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.UndefinedObject):
                cur.execute("SELECT * FROM users")
    finally:
        conn.rollback()
        conn.close()


def test_cross_tenant_set_local_returns_only_own_tenant_rows(two_tenants_with_users) -> None:
    data = two_tenants_with_users
    conn = psycopg2.connect(APP_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = %s", (str(data["tenant_a"]),))
            cur.execute("SELECT id FROM users")
            rows = {str(row[0]) for row in cur.fetchall()}
        conn.commit()
    finally:
        conn.close()

    assert str(data["user_a"]) in rows
    assert str(data["user_b"]) not in rows


def test_insert_with_mismatched_tenant_id_rejected_by_with_check(two_tenants_with_users) -> None:
    data = two_tenants_with_users
    conn = psycopg2.connect(APP_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = %s", (str(data["tenant_a"]),))
            # Postgres reports a WITH CHECK / RLS policy violation as
            # insufficient_privilege (SQLSTATE 42501), not a check
            # constraint violation.
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    "INSERT INTO users "
                    "(id, tenant_id, external_idp_subject, email, display_name) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        str(uuid.uuid4()),
                        # Row claims tenant_b while the session GUC is
                        # tenant_a -- WITH CHECK must reject this.
                        str(data["tenant_b"]),
                        "oid-smuggled",
                        "smuggled@example.com",
                        "Smuggled",
                    ),
                )
    finally:
        conn.rollback()
        conn.close()


def test_insert_matching_tenant_id_succeeds(two_tenants_with_users) -> None:
    data = two_tenants_with_users
    new_id = uuid.uuid4()
    conn = psycopg2.connect(APP_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = %s", (str(data["tenant_a"]),))
            cur.execute(
                "INSERT INTO users "
                "(id, tenant_id, external_idp_subject, email, display_name) "
                "VALUES (%s, %s, %s, %s, %s)",
                (str(new_id), str(data["tenant_a"]), "oid-ok", "ok@example.com", "Ok"),
            )
        conn.commit()
    finally:
        conn.close()

    # Confirm it's visible back under the same tenant context.
    conn = psycopg2.connect(APP_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL app.current_tenant_id = %s", (str(data["tenant_a"]),))
            cur.execute("SELECT id FROM users WHERE id = %s", (str(new_id),))
            assert cur.fetchone() is not None
        conn.commit()
    finally:
        conn.close()
