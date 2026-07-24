"""Task 11 (US-11): host/reception visit API routes (app/api/visits.py).

Gherkin Scenario 3 (approve), Scenario 4 (deny), Scenario 5 (invalid
transition is 409, not the target-status route the design deliberately
doesn't expose -- US-11 review, Should-fix #6: the concrete verifier call
is POST /visits/{id}/approve (or /deny) on an already-decided visit).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_token_validator
from app.auth.entra import EntraTokenValidator, StaticJWKSProvider
from app.crypto.envelope import LocalEnvelopeKeyProvider, get_envelope_key_provider
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
    app.dependency_overrides[get_envelope_key_provider] = lambda: LocalEnvelopeKeyProvider()
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    return TestClient(app)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_requested_visit_directly(tenant_id: uuid.UUID, host_user_id: uuid.UUID | None) -> uuid.UUID:
    import psycopg2

    from tests.conftest import MIGRATOR_DSN

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


def _setup_tenant_with_host() -> tuple[uuid.UUID, str, uuid.UUID, str]:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    host_oid = f"oid-host-{uuid.uuid4().hex[:8]}"
    host_user_id = insert_user(tenant_id, host_oid)
    assign_role(tenant_id, host_user_id, "host")
    return tenant_id, entra_tenant_id, host_user_id, host_oid


def test_host_can_approve_own_visit(client, idp) -> None:
    tenant_id, entra_tenant_id, host_user_id, host_oid = _setup_tenant_with_host()
    visit_id = _make_requested_visit_directly(tenant_id, host_user_id)
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)

    response = client.post(f"/visits/{visit_id}/approve", headers=_headers(token))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Registered"


def test_host_can_deny_own_visit_with_reason(client, idp) -> None:
    tenant_id, entra_tenant_id, host_user_id, host_oid = _setup_tenant_with_host()
    visit_id = _make_requested_visit_directly(tenant_id, host_user_id)
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)

    response = client.post(
        f"/visits/{visit_id}/deny", headers=_headers(token), json={"reason": "unknown visitor"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "Denied"


def test_deny_without_reason_is_422(client, idp) -> None:
    tenant_id, entra_tenant_id, host_user_id, host_oid = _setup_tenant_with_host()
    visit_id = _make_requested_visit_directly(tenant_id, host_user_id)
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)

    response = client.post(f"/visits/{visit_id}/deny", headers=_headers(token), json={"reason": ""})
    assert response.status_code == 422


def test_approve_by_non_owning_host_is_403(client, idp) -> None:
    tenant_id, entra_tenant_id, host_user_id, _ = _setup_tenant_with_host()
    visit_id = _make_requested_visit_directly(tenant_id, host_user_id)

    other_host_oid = f"oid-other-host-{uuid.uuid4().hex[:8]}"
    other_host_id = insert_user(tenant_id, other_host_oid)
    assign_role(tenant_id, other_host_id, "host")
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=other_host_oid)

    response = client.post(f"/visits/{visit_id}/approve", headers=_headers(token))
    assert response.status_code == 403


def test_approve_unresolved_host_visit_is_403_for_any_host(client, idp) -> None:
    tenant_id, entra_tenant_id, _host_user_id, _ = _setup_tenant_with_host()
    visit_id = _make_requested_visit_directly(tenant_id, None)  # unresolved host

    other_host_oid = f"oid-other-host-{uuid.uuid4().hex[:8]}"
    other_host_id = insert_user(tenant_id, other_host_oid)
    assign_role(tenant_id, other_host_id, "host")
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=other_host_oid)

    response = client.post(f"/visits/{visit_id}/approve", headers=_headers(token))
    assert response.status_code == 403


def test_approve_requires_approve_deny_visits_permission(client, idp) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    reception_oid = f"oid-reception-{uuid.uuid4().hex[:8]}"
    reception_id = insert_user(tenant_id, reception_oid)
    assign_role(tenant_id, reception_id, "reception_security")  # lacks approve_deny_visits
    visit_id = _make_requested_visit_directly(tenant_id, reception_id)

    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=reception_oid)
    response = client.post(f"/visits/{visit_id}/approve", headers=_headers(token))
    assert response.status_code == 403


def test_gherkin_scenario_5_approve_on_already_registered_visit_is_409(client, idp) -> None:
    tenant_id, entra_tenant_id, host_user_id, host_oid = _setup_tenant_with_host()
    visit_id = _make_requested_visit_directly(tenant_id, host_user_id)
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)

    first = client.post(f"/visits/{visit_id}/approve", headers=_headers(token))
    assert first.status_code == 200

    second = client.post(f"/visits/{visit_id}/approve", headers=_headers(token))
    assert second.status_code == 409

    unchanged = client.get(f"/visits/{visit_id}", headers=_headers(token))
    assert unchanged.json()["status"] == "Registered"  # still Registered from the first call


def test_deny_on_already_decided_visit_is_409(client, idp) -> None:
    tenant_id, entra_tenant_id, host_user_id, host_oid = _setup_tenant_with_host()
    visit_id = _make_requested_visit_directly(tenant_id, host_user_id)
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)

    first = client.post(f"/visits/{visit_id}/deny", headers=_headers(token), json={"reason": "no"})
    assert first.status_code == 200

    second = client.post(f"/visits/{visit_id}/deny", headers=_headers(token), json={"reason": "no again"})
    assert second.status_code == 409


def test_no_route_accepts_a_direct_transition_to_an_arbitrary_status(client, idp) -> None:
    """There is no route that accepts a target status/trigger at all -- the
    real safety property behind Gherkin Scenario 5 (US-11 review,
    Should-fix #6)."""
    openapi_paths = set(app.openapi()["paths"].keys())
    for path in openapi_paths:
        assert "{status}" not in path
        assert "{trigger}" not in path


def test_get_visit_cross_tenant_is_uniform_403(client, idp) -> None:
    tenant_a, entra_tenant_id_a, host_user_id, host_oid = _setup_tenant_with_host()
    tenant_b = insert_tenant("Globex", f"globex-entra-tid-{uuid.uuid4().hex[:8]}")
    other_oid = f"oid-other-{uuid.uuid4().hex[:8]}"
    other_user_id = insert_user(tenant_b, other_oid)
    assign_role(tenant_b, other_user_id, "reception_security")

    visit_id = _make_requested_visit_directly(tenant_a, host_user_id)
    token = idp.issue_token(tid=_entra_tid_of(tenant_b), aud=AUDIENCE, oid=other_oid)

    response = client.get(f"/visits/{visit_id}", headers=_headers(token))
    assert response.status_code == 403


def _entra_tid_of(tenant_id: uuid.UUID) -> str:
    import psycopg2

    from tests.conftest import MIGRATOR_DSN

    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT entra_tenant_id FROM tenants WHERE id = %s", (str(tenant_id),))
            (entra_tenant_id,) = cur.fetchone()
    finally:
        conn.close()
    return entra_tenant_id


def test_get_visit_nonexistent_is_uniform_403_not_404(client, idp) -> None:
    tenant_id, entra_tenant_id, host_user_id, host_oid = _setup_tenant_with_host()
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)

    response = client.get(f"/visits/{uuid.uuid4()}", headers=_headers(token))
    assert response.status_code == 403


def test_get_visit_cross_tenant_and_nonexistent_produce_identical_error_body(client, idp) -> None:
    tenant_a, entra_tenant_id_a, host_user_id, host_oid = _setup_tenant_with_host()
    tenant_b = insert_tenant("Globex", f"globex-entra-tid-{uuid.uuid4().hex[:8]}")
    other_oid = f"oid-other-{uuid.uuid4().hex[:8]}"
    other_user_id = insert_user(tenant_b, other_oid)
    assign_role(tenant_b, other_user_id, "reception_security")
    entra_tenant_id_b = _entra_tid_of(tenant_b)

    visit_id_in_tenant_a = _make_requested_visit_directly(tenant_a, host_user_id)
    token_b = idp.issue_token(tid=entra_tenant_id_b, aud=AUDIENCE, oid=other_oid)

    cross_tenant_response = client.get(f"/visits/{visit_id_in_tenant_a}", headers=_headers(token_b))
    nonexistent_response = client.get(f"/visits/{uuid.uuid4()}", headers=_headers(token_b))

    assert cross_tenant_response.status_code == nonexistent_response.status_code == 403
    assert cross_tenant_response.json()["detail"] == nonexistent_response.json()["detail"]
