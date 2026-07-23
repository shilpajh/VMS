"""Task 6 (US-10): tenant resolution + JIT provisioning
(app/auth/dependencies.get_current_principal), calling the dependency
function directly (no running FastAPI app needed -- routes are task 8).

Exercises the exact 3-step sequence from ADR-001 §1 end-to-end against real
Postgres/RLS, and the Gherkin scenarios "First-time SSO login JIT-provisions
a user with zero roles" and part of "Disabled user is rejected".
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select

from app.auth.dependencies import get_current_principal
from app.auth.entra import EntraTokenValidator, StaticJWKSProvider
from app.models import AuditEvent
from tests.conftest import insert_tenant, insert_user, set_user_status
from tests.support.entra_tokens import make_synthetic_idp

AUDIENCE = "api://smart-vms-core-api-dev-placeholder"


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.fixture()
def idp():
    return make_synthetic_idp()


@pytest.fixture()
def validator(idp):
    provider = StaticJWKSProvider({idp.kid: idp.public_key_pem})
    return EntraTokenValidator(jwks_provider=provider, audience=AUDIENCE)


async def test_first_login_jit_provisions_user_with_zero_roles(app_session, idp, validator):
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")

    # Refetch tenant's entra_tenant_id for the token.
    from app.models import Tenant

    entra_tenant_id = (
        await app_session.execute(select(Tenant.entra_tenant_id).where(Tenant.id == tenant_id))
    ).scalar_one()

    new_oid = f"new-oid-{uuid.uuid4().hex[:8]}"
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=new_oid)

    principal = await get_current_principal(
        credentials=_bearer(token), session=app_session, validator=validator
    )

    assert principal.tenant_id == tenant_id
    assert principal.external_idp_subject == new_oid
    assert principal.permissions == frozenset()  # least privilege: zero roles

    audit_row = (
        await app_session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id, AuditEvent.event_type == "user.provisioned"
            )
        )
    ).scalar_one()
    assert audit_row.actor == new_oid
    assert audit_row.correlation_id is not None
    assert audit_row.reason
    assert audit_row.target_type == "user"
    assert audit_row.target_id == principal.user_id


async def test_second_login_does_not_re_provision(app_session, idp, validator):
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    from app.models import Tenant

    entra_tenant_id = (
        await app_session.execute(select(Tenant.entra_tenant_id).where(Tenant.id == tenant_id))
    ).scalar_one()
    oid = f"repeat-oid-{uuid.uuid4().hex[:8]}"
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=oid)

    first = await get_current_principal(
        credentials=_bearer(token), session=app_session, validator=validator
    )
    second = await get_current_principal(
        credentials=_bearer(token), session=app_session, validator=validator
    )

    assert first.user_id == second.user_id

    provisioned_events = (
        await app_session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id, AuditEvent.event_type == "user.provisioned"
            )
        )
    ).scalars().all()
    assert len(provisioned_events) == 1  # not re-provisioned/re-audited on second login


async def test_unknown_tenant_is_rejected_with_401(app_session, idp, validator):
    token = idp.issue_token(tid="no-such-tenant-tid", aud=AUDIENCE)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(
            credentials=_bearer(token), session=app_session, validator=validator
        )
    assert exc_info.value.status_code == 401


async def test_suspended_tenant_is_rejected_with_401(app_session, idp, validator):
    entra_tenant_id = f"suspended-entra-tid-{uuid.uuid4().hex[:8]}"
    insert_tenant("Suspended Co", entra_tenant_id, status="suspended")
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(
            credentials=_bearer(token), session=app_session, validator=validator
        )
    assert exc_info.value.status_code == 401


async def test_disabled_user_is_rejected_with_401(app_session, idp, validator):
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    oid = f"disabled-oid-{uuid.uuid4().hex[:8]}"
    user_id = insert_user(tenant_id, oid, status="disabled")

    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=oid)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(
            credentials=_bearer(token), session=app_session, validator=validator
        )
    assert exc_info.value.status_code == 401
    set_user_status(user_id, "active")  # cleanup, harmless if not needed


async def test_missing_bearer_token_is_rejected_with_401(app_session, validator):
    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(credentials=None, session=app_session, validator=validator)
    assert exc_info.value.status_code == 401
