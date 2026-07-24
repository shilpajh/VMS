"""Task 7 (US-01): the US-01-specific version of the pattern
tests/test_visits_forged_token_cross_tenant.py required for US-11's own
routes -- proving tenant isolation directly against POST /visits/checkin,
not assumed inherited from US-11's route-level tests.

Two scenarios:
  1. A forged signature (idp not in the trusted JWKS set at all) -> 401,
     no state change.
  2. A genuinely trusted signature, but the principal's tenant differs from
     the code's owning tenant -> the SAME uniform 404 every other rejection
     cause produces (unlike US-11's uniform 403 -- this endpoint looks up
     by a high-entropy bearer secret, not an enumerable visit id, so 404
     closes the oracle the same way an unknown/expired code does; US-01
     plan, Part A Risks).
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
def trusted_idp():
    return make_synthetic_idp()


@pytest.fixture()
def forged_idp():
    return make_synthetic_idp()


@pytest.fixture(autouse=True)
def override_dependencies(trusted_idp, _migrated_schema):
    provider = StaticJWKSProvider({trusted_idp.kid: trusted_idp.public_key_pem})
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


def _make_registered_visit_directly(tenant_id: uuid.UUID, host_user_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    code = secrets.token_urlsafe(24)
    visit_id = uuid.uuid4()
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
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


def _setup_victim_tenant_with_registered_visit() -> tuple[uuid.UUID, str, uuid.UUID, str, uuid.UUID, str]:
    entra_tenant_id = f"victim-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Victim Co", entra_tenant_id)
    reception_oid = f"oid-victim-reception-{uuid.uuid4().hex[:8]}"
    reception_id = insert_user(tenant_id, reception_oid)
    assign_role(tenant_id, reception_id, "reception_security")
    host_id = insert_user(tenant_id, f"oid-victim-host-{uuid.uuid4().hex[:8]}")
    visit_id, code = _make_registered_visit_directly(tenant_id, host_id)
    return tenant_id, entra_tenant_id, reception_id, reception_oid, visit_id, code


def test_forged_signature_token_rejected_on_checkin(client, forged_idp) -> None:
    tenant_id, entra_tenant_id, reception_id, reception_oid, visit_id, code = (
        _setup_victim_tenant_with_registered_visit()
    )

    forged_token = forged_idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=reception_oid)
    response = client.post(
        "/visits/checkin", headers=_headers(forged_token), json={"checkin_code": code}
    )

    assert response.status_code == 401
    assert _visit_status(visit_id) == "Registered"


def test_forged_signature_with_garbage_tid_is_also_rejected_on_checkin(client, forged_idp) -> None:
    response = client.post(
        "/visits/checkin",
        headers=_headers(forged_idp.issue_token(tid="no-such-tenant-anywhere", aud=AUDIENCE)),
        json={"checkin_code": secrets.token_urlsafe(24)},
    )
    assert response.status_code == 401


def test_trusted_signature_wrong_tenant_gets_uniform_404_not_a_distinguishable_error(
    client, trusted_idp
) -> None:
    tenant_id, victim_entra_tid, reception_id, reception_oid, visit_id, code = (
        _setup_victim_tenant_with_registered_visit()
    )

    attacker_entra_tid = f"attacker-entra-tid-{uuid.uuid4().hex[:8]}"
    attacker_tenant_id = insert_tenant("Attacker Co", attacker_entra_tid)
    attacker_oid = f"oid-attacker-reception-{uuid.uuid4().hex[:8]}"
    attacker_user_id = insert_user(attacker_tenant_id, attacker_oid)
    assign_role(attacker_tenant_id, attacker_user_id, "reception_security")

    token = trusted_idp.issue_token(tid=attacker_entra_tid, aud=AUDIENCE, oid=attacker_oid)
    response = client.post("/visits/checkin", headers=_headers(token), json={"checkin_code": code})

    assert response.status_code == 404
    assert response.json()["detail"] == "invalid or expired check-in code"
    assert _visit_status(visit_id) == "Registered"  # no state change, no cross-tenant check-in
