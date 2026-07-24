"""Task 1 (US-07): the vms_purge role is NOBYPASSRLS with exactly the narrow
grants the purge needs -- the structural-isolation safety model (SP-B2)
depends on this role being subject to RLS, unlike vms_migrator (BYPASSRLS).
Runs against vms_test at head (0005 applied).
"""

from __future__ import annotations

import psycopg2

from tests.conftest import SUPERUSER_DSN


def _role_attr(rolname: str) -> dict:
    conn = psycopg2.connect(SUPERUSER_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rolbypassrls, rolsuper, rolcreatedb, rolcreaterole "
                "FROM pg_roles WHERE rolname=%s",
                (rolname,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None, f"role {rolname} does not exist"
    return {"bypassrls": row[0], "super": row[1], "createdb": row[2], "createrole": row[3]}


def test_vms_purge_is_nobypassrls_and_unprivileged() -> None:
    """The whole safety model rests on vms_purge being subject to RLS."""
    attrs = _role_attr("vms_purge")
    assert attrs["bypassrls"] is False, "vms_purge MUST NOT bypass RLS (SP-B2 structural isolation)"
    assert attrs["super"] is False
    assert attrs["createdb"] is False
    assert attrs["createrole"] is False


def _has_grant(rolname: str, table: str, privilege: str) -> bool:
    conn = psycopg2.connect(SUPERUSER_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.role_table_grants "
                "WHERE grantee=%s AND table_name=%s AND privilege_type=%s",
                (rolname, table, privilege),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def test_vms_purge_has_scrub_and_delete_grants() -> None:
    # Scrub (UPDATE) on the referenced/skeleton tables:
    assert _has_grant("vms_purge", "users", "UPDATE")
    assert _has_grant("vms_purge", "visits", "UPDATE")
    # Delete on the transient tables:
    assert _has_grant("vms_purge", "outbox_messages", "DELETE")
    assert _has_grant("vms_purge", "portal_contact_verifications", "DELETE")
    # Read what it needs + write the audit:
    assert _has_grant("vms_purge", "tenants", "SELECT")
    assert _has_grant("vms_purge", "retention_policies", "SELECT")
    assert _has_grant("vms_purge", "audit_events", "INSERT")


def test_vms_purge_has_no_delete_on_scrub_tables() -> None:
    """Scrub tables must be UPDATE-only for vms_purge -- a DELETE grant would
    let the purge hard-delete a referenced users/visits row, breaking the
    audit linkage the scrub-in-place design preserves."""
    assert not _has_grant("vms_purge", "users", "DELETE")
    assert not _has_grant("vms_purge", "visits", "DELETE")
    # And never touches the append-only audit beyond INSERT:
    assert not _has_grant("vms_purge", "audit_events", "DELETE")
    assert not _has_grant("vms_purge", "audit_events", "UPDATE")
