"""Task 11 (US-11): GET /visits scoping by view_visits (US-11 review,
Should-fix #7; Gherkin Scenario 1 "live visitor list" / Scenario 2
"cross-tenant isolation of portal submissions").

Reconciliation applied per the plan Part B: Scenario 1's "live visitor
list" is satisfied by querying as a view_visits holder (reception_security)
OR as the owning host -- an unrelated host without view_visits and without
ownership must NOT see it.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_token_validator
from app.auth.entra import EntraTokenValidator, StaticJWKSProvider
from app.db.session import get_session
from app.main import app
from tests.conftest import MIGRATOR_DSN, TestAppSessionLocal, assign_role, insert_tenant, insert_user
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


def _make_requested_visit_directly(tenant_id: uuid.UUID, host_user_id: uuid.UUID | None) -> uuid.UUID:
    visit_id = uuid.uuid4()
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO visits (id, tenant_id, status, visitor_full_name, "
                "contact_channel, contact_value, host_user_id, tracking_reference, "
                "privacy_notice_acknowledged, privacy_notice_version, correlation_id) "
                "VALUES (%s, %s, 'Requested', %s, 'email', %s, %s, %s, true, 'v1', %s)",
                (
                    str(visit_id),
                    str(tenant_id),
                    "Test Visitor",
                    f"visitor-{uuid.uuid4().hex[:8]}@example.com",
                    str(host_user_id) if host_user_id else None,
                    f"REQ-{uuid.uuid4().int % 10**12:012d}",
                    str(uuid.uuid4()),
                ),
            )
    finally:
        conn.close()
    return visit_id


def test_reception_security_view_visits_holder_sees_full_tenant_list(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    host_oid = f"oid-host-{uuid.uuid4().hex[:8]}"
    host_id = insert_user(tenant_id, host_oid)
    assign_role(tenant_id, host_id, "host")
    visit_id = _make_requested_visit_directly(tenant_id, host_id)

    reception_oid = f"oid-reception-{uuid.uuid4().hex[:8]}"
    reception_id = insert_user(tenant_id, reception_oid)
    assign_role(tenant_id, reception_id, "reception_security")

    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=reception_oid)
    response = client.get("/visits", headers=_headers(token))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert str(visit_id) in ids


def test_owning_host_sees_own_visit_in_list(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    host_oid = f"oid-host-{uuid.uuid4().hex[:8]}"
    host_id = insert_user(tenant_id, host_oid)
    assign_role(tenant_id, host_id, "host")
    visit_id = _make_requested_visit_directly(tenant_id, host_id)

    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)
    response = client.get("/visits", headers=_headers(token))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert str(visit_id) in ids


def test_unrelated_host_without_view_visits_does_not_see_others_visit(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    host_oid = f"oid-host-{uuid.uuid4().hex[:8]}"
    host_id = insert_user(tenant_id, host_oid)
    assign_role(tenant_id, host_id, "host")
    visit_id = _make_requested_visit_directly(tenant_id, host_id)

    other_host_oid = f"oid-other-host-{uuid.uuid4().hex[:8]}"
    other_host_id = insert_user(tenant_id, other_host_oid)
    assign_role(tenant_id, other_host_id, "host")  # host lacks view_visits

    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=other_host_oid)
    response = client.get("/visits", headers=_headers(token))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert str(visit_id) not in ids


def test_cross_tenant_globex_user_never_sees_acme_visit(client, idp) -> None:
    """Gherkin Scenario 2: cross-tenant isolation of portal submissions."""
    acme_entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    acme_tenant_id = insert_tenant("Acme", acme_entra_tenant_id)
    host_oid = f"oid-host-{uuid.uuid4().hex[:8]}"
    host_id = insert_user(acme_tenant_id, host_oid)
    assign_role(acme_tenant_id, host_id, "host")
    visit_id = _make_requested_visit_directly(acme_tenant_id, host_id)

    globex_entra_tenant_id = f"globex-entra-tid-{uuid.uuid4().hex[:8]}"
    globex_tenant_id = insert_tenant("Globex", globex_entra_tenant_id)
    globex_oid = f"oid-globex-{uuid.uuid4().hex[:8]}"
    globex_user_id = insert_user(globex_tenant_id, globex_oid)
    assign_role(globex_tenant_id, globex_user_id, "reception_security")  # even with view_visits

    token = idp.issue_token(tid=globex_entra_tenant_id, aud=AUDIENCE, oid=globex_oid)
    response = client.get("/visits", headers=_headers(token))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert str(visit_id) not in ids

    get_response = client.get(f"/visits/{visit_id}", headers=_headers(token))
    assert get_response.status_code == 403
