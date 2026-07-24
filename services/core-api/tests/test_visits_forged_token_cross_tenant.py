"""Task 13 (US-11): US-11-specific forged-token/wrong-tid cross-tenant test.

The design-gate review (docs/reviews/US-11-review.md, B1) found that US-11's
host endpoints derive BOTH the RLS tenant-scoping GUC and the ownership
check entirely from `get_current_principal` -- the same function carrying
US-10's still-open B1 auth-bypass finding. The remediation is a hard
merge/ship gate (US-11 may not ship until US-10's B1 is fixed), but this
plan's Definition of Done ALSO requires proving -- directly against US-11's
OWN new endpoints, not just inherited from US-10's identity-route tests --
that a forged/wrong-tid principal is rejected with no state change and no
cross-tenant read, on all three authenticated routes
(`/visits/{id}/approve`, `/deny`, `GET /visits`). This file is that
dedicated, independent proof.

Two forgery scenarios, both required by the review:
  1. A token signed by an idp NOT in the trusted JWKS set at all (a truly
     "forged" signature) -- must be rejected 401 by the identical
     get_current_principal dependency wiring at these NEW routes, not
     assumed from US-10's own tests.
  2. A token with a genuine trusted signature but whose `tid` resolves to a
     DIFFERENT tenant than the one owning the target visit -- proves tenant
     scoping (SET LOCAL + the 403 ownership contract) holds independently
     at this new surface, regardless of whether US-10's B1 is fixed yet.
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
def trusted_idp():
    return make_synthetic_idp()


@pytest.fixture()
def forged_idp():
    """A DIFFERENT synthetic idp (own keypair) NOT registered in the
    trusted JWKS set the validator is built with -- a truly forged
    signature, not merely an unusual claim set."""
    return make_synthetic_idp()


@pytest.fixture(autouse=True)
def override_dependencies(trusted_idp, _migrated_schema):
    # Only trusted_idp's kid is registered -- forged_idp's signature can
    # never verify against this validator, exactly mirroring how a real
    # HttpJWKSProvider would never trust a key it hasn't fetched/cached.
    # Issuer-pinning itself is proven by EntraTokenValidator.validate()'s own
    # issuer=expected_issuer check (US-10 B1 remediation), not by this
    # test double's key lookup -- see StaticJWKSProvider's docstring.
    provider = StaticJWKSProvider({trusted_idp.kid: trusted_idp.public_key_pem})
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


def _visit_status(visit_id: uuid.UUID) -> str:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM visits WHERE id = %s", (str(visit_id),))
            (status_,) = cur.fetchone()
    finally:
        conn.close()
    return status_


def _setup_victim_tenant_with_requested_visit() -> tuple[uuid.UUID, str, uuid.UUID, str, uuid.UUID]:
    entra_tenant_id = f"victim-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Victim Co", entra_tenant_id)
    host_oid = f"oid-victim-host-{uuid.uuid4().hex[:8]}"
    host_user_id = insert_user(tenant_id, host_oid)
    assign_role(tenant_id, host_user_id, "host")
    visit_id = _make_requested_visit_directly(tenant_id, host_user_id)
    return tenant_id, entra_tenant_id, host_user_id, host_oid, visit_id


# --- Scenario 1: a signature that fails verification entirely (forged idp,
# not in the trusted JWKS set) -- 401, no state change, on all three routes.


def test_forged_signature_token_rejected_on_approve(client, forged_idp) -> None:
    tenant_id, entra_tenant_id, host_user_id, host_oid, visit_id = _setup_victim_tenant_with_requested_visit()

    forged_token = forged_idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)
    response = client.post(f"/visits/{visit_id}/approve", headers=_headers(forged_token))

    assert response.status_code == 401
    assert _visit_status(visit_id) == "Requested"  # no state change


def test_forged_signature_token_rejected_on_deny(client, forged_idp) -> None:
    tenant_id, entra_tenant_id, host_user_id, host_oid, visit_id = _setup_victim_tenant_with_requested_visit()

    forged_token = forged_idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)
    response = client.post(
        f"/visits/{visit_id}/deny", headers=_headers(forged_token), json={"reason": "forged"}
    )

    assert response.status_code == 401
    assert _visit_status(visit_id) == "Requested"


def test_forged_signature_token_rejected_on_list_visits(client, forged_idp) -> None:
    tenant_id, entra_tenant_id, host_user_id, host_oid, visit_id = _setup_victim_tenant_with_requested_visit()

    forged_token = forged_idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=host_oid)
    response = client.get("/visits", headers=_headers(forged_token))

    assert response.status_code == 401


def test_forged_signature_with_garbage_tid_is_also_rejected(client, forged_idp) -> None:
    """Belt-and-suspenders: a forged token whose tid doesn't correspond to
    ANY real tenant at all is rejected identically."""
    response = client.get(
        "/visits",
        headers=_headers(forged_idp.issue_token(tid="no-such-tenant-anywhere", aud=AUDIENCE)),
    )
    assert response.status_code == 401


# --- Scenario 2: a genuinely trusted signature, but tid resolves to a
# DIFFERENT tenant than the one that owns the target visit -- 403 (tenant
# scoping holds), no cross-tenant read, no state change.


def test_trusted_signature_wrong_tenant_cannot_approve_victims_visit(client, trusted_idp) -> None:
    tenant_id, victim_entra_tid, host_user_id, host_oid, visit_id = _setup_victim_tenant_with_requested_visit()

    attacker_entra_tid = f"attacker-entra-tid-{uuid.uuid4().hex[:8]}"
    attacker_tenant_id = insert_tenant("Attacker Co", attacker_entra_tid)
    attacker_oid = f"oid-attacker-{uuid.uuid4().hex[:8]}"
    attacker_user_id = insert_user(attacker_tenant_id, attacker_oid)
    assign_role(attacker_tenant_id, attacker_user_id, "host")

    token = trusted_idp.issue_token(tid=attacker_entra_tid, aud=AUDIENCE, oid=attacker_oid)
    response = client.post(f"/visits/{visit_id}/approve", headers=_headers(token))

    assert response.status_code == 403
    assert _visit_status(visit_id) == "Requested"  # no state change


def test_trusted_signature_wrong_tenant_cannot_deny_victims_visit(client, trusted_idp) -> None:
    tenant_id, victim_entra_tid, host_user_id, host_oid, visit_id = _setup_victim_tenant_with_requested_visit()

    attacker_entra_tid = f"attacker-entra-tid-{uuid.uuid4().hex[:8]}"
    attacker_tenant_id = insert_tenant("Attacker Co", attacker_entra_tid)
    attacker_oid = f"oid-attacker-{uuid.uuid4().hex[:8]}"
    attacker_user_id = insert_user(attacker_tenant_id, attacker_oid)
    assign_role(attacker_tenant_id, attacker_user_id, "host")

    token = trusted_idp.issue_token(tid=attacker_entra_tid, aud=AUDIENCE, oid=attacker_oid)
    response = client.post(
        f"/visits/{visit_id}/deny", headers=_headers(token), json={"reason": "attacker"}
    )

    assert response.status_code == 403
    assert _visit_status(visit_id) == "Requested"


def test_trusted_signature_wrong_tenant_list_visits_never_leaks_victims_visit(client, trusted_idp) -> None:
    tenant_id, victim_entra_tid, host_user_id, host_oid, visit_id = _setup_victim_tenant_with_requested_visit()

    attacker_entra_tid = f"attacker-entra-tid-{uuid.uuid4().hex[:8]}"
    attacker_tenant_id = insert_tenant("Attacker Co", attacker_entra_tid)
    attacker_oid = f"oid-attacker-{uuid.uuid4().hex[:8]}"
    attacker_user_id = insert_user(attacker_tenant_id, attacker_oid)
    assign_role(attacker_tenant_id, attacker_user_id, "reception_security")  # even with view_visits

    token = trusted_idp.issue_token(tid=attacker_entra_tid, aud=AUDIENCE, oid=attacker_oid)
    response = client.get("/visits", headers=_headers(token))

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert str(visit_id) not in ids


def test_trusted_signature_wrong_tenant_get_visit_by_id_is_uniform_403(client, trusted_idp) -> None:
    tenant_id, victim_entra_tid, host_user_id, host_oid, visit_id = _setup_victim_tenant_with_requested_visit()

    attacker_entra_tid = f"attacker-entra-tid-{uuid.uuid4().hex[:8]}"
    attacker_tenant_id = insert_tenant("Attacker Co", attacker_entra_tid)
    attacker_oid = f"oid-attacker-{uuid.uuid4().hex[:8]}"
    attacker_user_id = insert_user(attacker_tenant_id, attacker_oid)
    assign_role(attacker_tenant_id, attacker_user_id, "reception_security")

    token = trusted_idp.issue_token(tid=attacker_entra_tid, aud=AUDIENCE, oid=attacker_oid)
    response = client.get(f"/visits/{visit_id}", headers=_headers(token))

    assert response.status_code == 403
