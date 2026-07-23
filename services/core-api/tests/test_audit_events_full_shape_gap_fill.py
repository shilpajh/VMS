"""Audit-event 5-field-shape coverage gap fill (US-10 /verify-story).

tests/test_audit_events.py's parametrized
`test_each_identity_event_type_is_writable_and_queryable` only asserts a row
count of 1 for `user.enabled` and `role.revoked` -- it never asserts the
actual field VALUES (actor/reason/correlation_id/target ref) the way
`test_write_audit_event_records_all_required_fields` does for
`role.assigned`. Likewise `tests/test_bootstrap_tenant.py`'s
`tenant.created` check asserts only `actor`/`tenant_id`, not
`reason`/`correlation_id`/timestamp.

This file closes that gap for the three under-asserted event types, and
does so via the REAL workflow (the actual PATCH/DELETE routes and the real
`bootstrap_tenant` script), not by calling `write_audit_event` directly --
so it also confirms the real call sites pass every field, not just that the
helper function is capable of storing them.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_token_validator
from app.auth.entra import EntraTokenValidator, StaticJWKSProvider
from app.db.session import get_session
from app.domain.rbac import PERMISSION_POLICY_VERSION
from app.main import app
from app.models.tenant import PLATFORM_TENANT_ID
from scripts.bootstrap_tenant import bootstrap_tenant
from tests.conftest import (
    MIGRATOR_DSN,
    TestAppSessionLocal,
    assign_role,
    insert_tenant,
    insert_user,
)
from tests.support.entra_tokens import make_synthetic_idp

AUDIENCE = "api://smart-vms-core-api-dev-placeholder"


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
def override_dependencies(idp, _migrated_schema):
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


def _fetch_audit_row(tenant_id: uuid.UUID, event_type: str, target_id: uuid.UUID) -> tuple:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT actor, reason, correlation_id, target_type, target_id, "
                "created_at, policy_version "
                "FROM audit_events "
                "WHERE tenant_id = %s AND event_type = %s AND target_id = %s",
                (str(tenant_id), event_type, str(target_id)),
            )
            row = cur.fetchone()
        return row
    finally:
        conn.close()


def test_user_enabled_audit_event_via_real_api_has_full_5_field_shape(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)

    admin_oid = f"oid-admin-{uuid.uuid4().hex[:8]}"
    admin_user_id = insert_user(tenant_id, admin_oid)
    assign_role(tenant_id, admin_user_id, "tenant_admin")
    admin_token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=admin_oid)

    target_oid = f"oid-target-{uuid.uuid4().hex[:8]}"
    target_user_id = insert_user(tenant_id, target_oid, status="disabled")

    response = client.patch(
        f"/tenants/{tenant_id}/users/{target_user_id}",
        headers=_headers(admin_token),
        json={"status": "active", "reason": "re-enabled after review"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"

    row = _fetch_audit_row(tenant_id, "user.enabled", target_user_id)
    assert row is not None, "no user.enabled audit row was written by the real PATCH workflow"
    actor, reason, correlation_id, target_type, target_id, created_at, policy_version = row

    assert actor == admin_oid
    assert reason == "re-enabled after review"
    assert correlation_id is not None
    assert target_type == "user"
    assert str(target_id) == str(target_user_id)
    assert created_at is not None
    # user.enabled is not a role change -- no policy_version expected.
    assert policy_version is None


def test_role_revoked_audit_event_via_real_api_has_full_5_field_shape(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)

    admin_oid = f"oid-admin-{uuid.uuid4().hex[:8]}"
    admin_user_id = insert_user(tenant_id, admin_oid)
    assign_role(tenant_id, admin_user_id, "tenant_admin")
    admin_token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=admin_oid)

    target_oid = f"oid-target-{uuid.uuid4().hex[:8]}"
    target_user_id = insert_user(tenant_id, target_oid)
    assign_role(tenant_id, target_user_id, "reception_security")

    roles_response = client.get("/roles", headers=_headers(admin_token))
    role_id = next(r["id"] for r in roles_response.json() if r["code"] == "reception_security")

    response = client.delete(
        f"/tenants/{tenant_id}/users/{target_user_id}/roles/{role_id}"
        "?reason=no_longer_reception_staff",
        headers=_headers(admin_token),
    )
    assert response.status_code == 204

    row = _fetch_audit_row(tenant_id, "role.revoked", target_user_id)
    assert row is not None, "no role.revoked audit row was written by the real DELETE workflow"
    actor, reason, correlation_id, target_type, target_id, created_at, policy_version = row

    assert actor == admin_oid
    assert reason == "no_longer_reception_staff"
    assert correlation_id is not None
    assert target_type == "user"
    assert str(target_id) == str(target_user_id)
    assert created_at is not None
    # role.revoked IS a role change -- policy_version must be recorded.
    assert policy_version == PERMISSION_POLICY_VERSION


def test_tenant_created_audit_event_has_full_5_field_shape(_migrated_schema) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    result = bootstrap_tenant(
        tenant_name="Acme Corp",
        entra_tenant_id=entra_tenant_id,
        admin_external_idp_subject=f"oid-admin-{uuid.uuid4().hex[:8]}",
        admin_email="admin@acme.example",
        admin_display_name="Acme Admin",
        dsn=MIGRATOR_DSN,
    )
    tenant_id = result["tenant_id"]

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT actor, reason, correlation_id, target_type, target_id, "
                "created_at, tenant_id "
                "FROM audit_events WHERE event_type = 'tenant.created' AND target_id = %s",
                (str(tenant_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    assert row is not None
    actor, reason, correlation_id, target_type, target_id, created_at, audit_tenant_id = row

    assert actor == "system"
    assert reason  # non-empty, non-null -- exact string ("ops_bootstrap") is an implementation detail
    assert correlation_id is not None
    assert target_type == "tenant"
    assert str(target_id) == str(tenant_id)
    assert created_at is not None
    # tenant.created is attributed to the reserved sentinel platform tenant,
    # never to the newly created tenant itself (there is no human platform
    # operator under that tenant -- ADR-001 SS4/SS9).
    assert str(audit_tenant_id) == str(PLATFORM_TENANT_ID)
