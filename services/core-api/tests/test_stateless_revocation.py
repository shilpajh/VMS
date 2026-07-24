"""Task 10 (US-10): stateless-revocation re-check.

Exercises the exact Gherkin scenario "Disabled user is rejected on next
request despite a still-valid token": a user is disabled mid-session by a
tenant_admin; their still-unexpired Entra access token is presented again on
a later request and must be rejected (401) -- disabled/suspended status is
re-checked against current DB state on every call
(app.auth.dependencies.get_current_principal), never cached/trusted from
token-mint time.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.dependencies import get_token_validator
from app.auth.entra import EntraTokenValidator, StaticJWKSProvider
from app.db.session import get_session
from app.main import app
from app.models import AuditEvent
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


def test_disabled_user_rejected_on_next_request_despite_still_valid_token(
    client, idp, app_session
) -> None:
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)

    admin_oid = f"oid-admin-{uuid.uuid4().hex[:8]}"
    admin_user_id = insert_user(tenant_id, admin_oid)
    assign_role(tenant_id, admin_user_id, "tenant_admin")
    admin_token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=admin_oid)

    target_oid = f"oid-priya-{uuid.uuid4().hex[:8]}"
    target_user_id = insert_user(tenant_id, target_oid)
    # A long-lived, still-unexpired token -- the whole point of the
    # scenario is that this token is NOT expired when reused after disable.
    target_token = idp.issue_token(
        tid=entra_tenant_id, aud=AUDIENCE, oid=target_oid, expires_in_seconds=3600
    )

    # 1. Confirm the token works before disabling (an active session).
    pre_disable_response = client.get("/me", headers=_headers(target_token))
    assert pre_disable_response.status_code == 200

    # 2. tenant_admin disables the user mid-session.
    disable_response = client.patch(
        f"/tenants/{tenant_id}/users/{target_user_id}",
        headers=_headers(admin_token),
        json={"status": "disabled", "reason": "left the company"},
    )
    assert disable_response.status_code == 200
    assert disable_response.json()["status"] == "disabled"

    # 3. The SAME still-valid (unexpired) token is rejected on the next call.
    post_disable_response = client.get("/me", headers=_headers(target_token))
    assert post_disable_response.status_code == 401


async def test_user_disabled_audit_event_has_actor_reason_and_correlation_id(app_session) -> None:
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    from tests.conftest import set_tenant_context

    await set_tenant_context(app_session, tenant_id)

    from app.domain.audit import write_audit_event

    target_user_id = uuid.uuid4()
    await write_audit_event(
        app_session,
        tenant_id=tenant_id,
        event_type="user.disabled",
        actor="oid-admin",
        target_type="user",
        target_id=target_user_id,
        reason="left the company",
        correlation_id=uuid.uuid4(),
    )

    row = (
        await app_session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id, AuditEvent.event_type == "user.disabled"
            )
        )
    ).scalar_one()
    assert row.actor == "oid-admin"
    assert row.reason == "left the company"
    assert row.correlation_id is not None
    assert row.target_id == target_user_id
