"""Task 6 (US-01): POST /visits/checkin (app/api/visits.py, app/api/dtos/visits.py).

Gherkin Scenarios 1/2/4 (Scenario 3, cross-tenant, lives in
tests/test_visit_checkin_tenant_isolation.py alongside its forged-token
counterpart -- task 7). Mirrors tests/test_visits_api_routes.py's fixture
pattern.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_token_validator
from app.auth.entra import EntraTokenValidator, StaticJWKSProvider
from app.crypto.envelope import LocalEnvelopeKeyProvider, get_envelope_key_provider
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
    app.dependency_overrides[get_envelope_key_provider] = lambda: LocalEnvelopeKeyProvider()
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    return TestClient(app)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_registered_visit_directly(
    tenant_id: uuid.UUID,
    host_user_id: uuid.UUID,
    *,
    checkin_code: str | None = None,
    expires_delta: timedelta = timedelta(days=7),
) -> tuple[uuid.UUID, str]:
    code = checkin_code or secrets.token_urlsafe(24)
    visit_id = uuid.uuid4()
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + expires_delta
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO visits (id, tenant_id, status, visitor_full_name, "
                "contact_channel, contact_value, host_user_id, tracking_reference, "
                "checkin_code_hash, checkin_code_expires_at, "
                "privacy_notice_acknowledged, privacy_notice_version, correlation_id) "
                "VALUES (%s, %s, 'Registered', %s, 'email', %s, %s, %s, %s, %s, true, 'v1', %s)",
                (
                    str(visit_id),
                    str(tenant_id),
                    "Test Visitor",
                    f"visitor-{uuid.uuid4().hex[:8]}@example.com",
                    str(host_user_id),
                    f"REQ-{uuid.uuid4().int % 10**12:012d}",
                    code_hash,
                    expires_at,
                    str(uuid.uuid4()),
                ),
            )
    finally:
        conn.close()
    return visit_id, code


def _visit_status(visit_id: uuid.UUID) -> str:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM visits WHERE id = %s", (str(visit_id),))
            (status_,) = cur.fetchone()
    finally:
        conn.close()
    return status_


def _setup_tenant_with_reception() -> tuple[uuid.UUID, str, uuid.UUID, str, uuid.UUID]:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    reception_oid = f"oid-reception-{uuid.uuid4().hex[:8]}"
    reception_id = insert_user(tenant_id, reception_oid)
    assign_role(tenant_id, reception_id, "reception_security")
    host_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    assign_role(tenant_id, host_id, "host")
    return tenant_id, entra_tenant_id, reception_id, reception_oid, host_id


def test_valid_code_checks_in_and_returns_checked_in(client, idp) -> None:
    tenant_id, entra_tenant_id, reception_id, reception_oid, host_id = _setup_tenant_with_reception()
    visit_id, code = _make_registered_visit_directly(tenant_id, host_id)
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=reception_oid)

    response = client.post("/visits/checkin", headers=_headers(token), json={"checkin_code": code})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CheckedIn"
    assert "checked_in_at" in body


def test_expired_code_is_uniform_404(client, idp) -> None:
    tenant_id, entra_tenant_id, reception_id, reception_oid, host_id = _setup_tenant_with_reception()
    visit_id, code = _make_registered_visit_directly(
        tenant_id, host_id, expires_delta=timedelta(seconds=-1)
    )
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=reception_oid)

    response = client.post("/visits/checkin", headers=_headers(token), json={"checkin_code": code})

    assert response.status_code == 404
    assert response.json()["detail"] == "invalid or expired check-in code"
    assert _visit_status(visit_id) == "Registered"


def test_unknown_code_is_the_same_uniform_404(client, idp) -> None:
    tenant_id, entra_tenant_id, reception_id, reception_oid, host_id = _setup_tenant_with_reception()
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=reception_oid)

    response = client.post(
        "/visits/checkin", headers=_headers(token), json={"checkin_code": secrets.token_urlsafe(24)}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "invalid or expired check-in code"


def test_already_checked_in_code_is_the_same_uniform_404(client, idp) -> None:
    tenant_id, entra_tenant_id, reception_id, reception_oid, host_id = _setup_tenant_with_reception()
    visit_id, code = _make_registered_visit_directly(tenant_id, host_id)
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=reception_oid)

    first = client.post("/visits/checkin", headers=_headers(token), json={"checkin_code": code})
    assert first.status_code == 200

    second = client.post("/visits/checkin", headers=_headers(token), json={"checkin_code": code})
    assert second.status_code == 404
    assert second.json()["detail"] == "invalid or expired check-in code"


def test_caller_without_checkin_confirm_is_403(client, idp) -> None:
    tenant_id, entra_tenant_id, reception_id, reception_oid, host_id = _setup_tenant_with_reception()
    visit_id, code = _make_registered_visit_directly(tenant_id, host_id)
    host_oid = f"oid-host2-{uuid.uuid4().hex[:8]}"
    host_only_id = insert_user(tenant_id, host_oid)
    assign_role(tenant_id, host_only_id, "host")  # lacks checkin_confirm
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)

    response = client.post("/visits/checkin", headers=_headers(token), json={"checkin_code": code})

    assert response.status_code == 403
    assert _visit_status(visit_id) == "Registered"


def test_response_never_includes_checkin_code_hash_or_plaintext_code(client, idp) -> None:
    tenant_id, entra_tenant_id, reception_id, reception_oid, host_id = _setup_tenant_with_reception()
    visit_id, code = _make_registered_visit_directly(tenant_id, host_id)
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=reception_oid)

    response = client.post("/visits/checkin", headers=_headers(token), json={"checkin_code": code})

    assert response.status_code == 200
    body_text = response.text
    assert "checkin_code_hash" not in body_text
    assert code not in body_text
