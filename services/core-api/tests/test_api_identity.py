"""Task 8 (US-10): API routes + DTOs (app/api/identity.py).

Exercises the full HTTP surface via FastAPI's TestClient, with the session
and token-validator dependencies overridden to point at vms_test and a
synthetic (locally signed) Entra token respectively -- never a real DB
default or a real Entra endpoint.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_token_validator
from app.auth.entra import EntraTokenValidator, StaticJWKSProvider
from app.db.session import get_session
from app.main import app
from tests.conftest import TestAppSessionLocal, assign_role, insert_tenant, insert_user
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


def test_get_me_returns_zero_roles_for_new_user(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    insert_tenant("Acme", entra_tenant_id)
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=f"oid-{uuid.uuid4().hex[:8]}")

    response = client.get("/me", headers=_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert body["roles"] == []
    assert body["permissions"] == []
    assert "external_idp_subject" not in body


def test_get_me_without_token_is_401(client) -> None:
    response = client.get("/me")
    assert response.status_code == 401


def test_cross_tenant_users_list_is_403(client, idp) -> None:
    entra_tenant_id_a = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_a = insert_tenant("Acme", entra_tenant_id_a)
    tenant_b = insert_tenant("Globex", f"globex-entra-tid-{uuid.uuid4().hex[:8]}")

    admin_oid = f"oid-admin-{uuid.uuid4().hex[:8]}"
    admin_user_id = insert_user(tenant_a, admin_oid)
    assign_role(tenant_a, admin_user_id, "tenant_admin")

    token = idp.issue_token(tid=entra_tenant_id_a, aud=AUDIENCE, oid=admin_oid)

    response = client.get(f"/tenants/{tenant_b}/users", headers=_headers(token))
    assert response.status_code == 403


def test_same_tenant_users_list_requires_manage_users_permission(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    host_oid = f"oid-host-{uuid.uuid4().hex[:8]}"
    host_user_id = insert_user(tenant_id, host_oid)
    assign_role(tenant_id, host_user_id, "host")  # host lacks manage_users

    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)
    response = client.get(f"/tenants/{tenant_id}/users", headers=_headers(token))
    assert response.status_code == 403


def test_tenant_admin_can_manage_users_and_roles(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    admin_oid = f"oid-admin-{uuid.uuid4().hex[:8]}"
    admin_user_id = insert_user(tenant_id, admin_oid)
    assign_role(tenant_id, admin_user_id, "tenant_admin")

    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=admin_oid)

    list_response = client.get(f"/tenants/{tenant_id}/users", headers=_headers(token))
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    create_response = client.post(
        f"/tenants/{tenant_id}/users",
        headers=_headers(token),
        json={
            "external_idp_subject": f"oid-new-{uuid.uuid4().hex[:8]}",
            "email": "new@example.com",
            "display_name": "New User",
        },
    )
    assert create_response.status_code == 201
    new_user_id = create_response.json()["id"]

    roles_response = client.get("/roles", headers=_headers(token))
    assert roles_response.status_code == 200
    reception_role_id = next(
        r["id"] for r in roles_response.json() if r["code"] == "reception_security"
    )

    assign_response = client.post(
        f"/tenants/{tenant_id}/users/{new_user_id}/roles",
        headers=_headers(token),
        json={"role_id": reception_role_id, "reason": "onboarding"},
    )
    assert assign_response.status_code == 201

    list_roles_response = client.get(
        f"/tenants/{tenant_id}/users/{new_user_id}/roles", headers=_headers(token)
    )
    assert list_roles_response.status_code == 200
    assert list_roles_response.json()[0]["role_code"] == "reception_security"

    revoke_response = client.delete(
        f"/tenants/{tenant_id}/users/{new_user_id}/roles/{reception_role_id}?reason=offboarding",
        headers=_headers(token),
    )
    assert revoke_response.status_code == 204


def test_disable_user_via_patch_requires_reason(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    admin_oid = f"oid-admin-{uuid.uuid4().hex[:8]}"
    admin_user_id = insert_user(tenant_id, admin_oid)
    assign_role(tenant_id, admin_user_id, "tenant_admin")

    target_oid = f"oid-target-{uuid.uuid4().hex[:8]}"
    target_user_id = insert_user(tenant_id, target_oid)

    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=admin_oid)

    missing_reason_response = client.patch(
        f"/tenants/{tenant_id}/users/{target_user_id}",
        headers=_headers(token),
        json={"status": "disabled", "reason": ""},
    )
    assert missing_reason_response.status_code == 422

    response = client.patch(
        f"/tenants/{tenant_id}/users/{target_user_id}",
        headers=_headers(token),
        json={"status": "disabled", "reason": "left the company"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"


def test_patch_unknown_user_in_own_tenant_is_404(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    admin_oid = f"oid-admin-{uuid.uuid4().hex[:8]}"
    admin_user_id = insert_user(tenant_id, admin_oid)
    assign_role(tenant_id, admin_user_id, "tenant_admin")

    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=admin_oid)

    response = client.patch(
        f"/tenants/{tenant_id}/users/{uuid.uuid4()}",
        headers=_headers(token),
        json={"status": "disabled", "reason": "n/a"},
    )
    assert response.status_code == 404


def test_no_platform_tenant_creation_route_exists(client) -> None:
    openapi_paths = set(app.openapi()["paths"].keys())
    assert not any("platform" in path for path in openapi_paths)
