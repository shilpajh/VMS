"""Task 7 (US-10): RBAC resolution (app/domain/rbac.py) against the full
ADR-001 §3 seed matrix -- especially `reception_security` -> `approve_deny_holds`
= true and `host` -> same = false, the compatibility guarantee
visit-lifecycle.yaml's `required_permission: approve_deny_holds` depends on.
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.rbac import get_user_permissions, has_permission
from tests.conftest import assign_role, insert_tenant, insert_user, set_tenant_context

SEED_MATRIX = {
    "tenant_admin": {"manage_users", "manage_roles", "view_dashboards"},
    "host": {"approve_deny_visits"},
    "reception_security": {"approve_deny_holds", "checkin_confirm"},
    "dashboard_viewer": {"view_dashboards"},
}

ALL_PERMISSIONS = {p for perms in SEED_MATRIX.values() for p in perms}


@pytest.fixture()
def tenant_id():
    return insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")


@pytest.mark.parametrize("role_code,expected_permissions", SEED_MATRIX.items())
async def test_role_resolves_exactly_its_seeded_permissions(
    app_session, tenant_id, role_code, expected_permissions
):
    user_id = insert_user(tenant_id, f"oid-{role_code}-{uuid.uuid4().hex[:8]}")
    assign_role(tenant_id, user_id, role_code)

    await set_tenant_context(app_session, tenant_id)
    permissions = await get_user_permissions(app_session, tenant_id, user_id)

    assert permissions == expected_permissions
    for permission_code in ALL_PERMISSIONS - expected_permissions:
        assert not await has_permission(app_session, tenant_id, user_id, permission_code)
    for permission_code in expected_permissions:
        assert await has_permission(app_session, tenant_id, user_id, permission_code)


async def test_reception_security_can_approve_deny_holds_but_host_cannot(app_session, tenant_id):
    """The exact compatibility guarantee visit-lifecycle.yaml's
    `required_permission: approve_deny_holds` on both Held-exit transitions
    depends on (ADR-001 §3)."""
    security_user = insert_user(tenant_id, f"oid-security-{uuid.uuid4().hex[:8]}")
    assign_role(tenant_id, security_user, "reception_security")

    host_user = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    assign_role(tenant_id, host_user, "host")

    await set_tenant_context(app_session, tenant_id)

    assert await has_permission(app_session, tenant_id, security_user, "approve_deny_holds") is True
    assert await has_permission(app_session, tenant_id, host_user, "approve_deny_holds") is False


async def test_user_with_zero_roles_has_zero_permissions(app_session, tenant_id):
    user_id = insert_user(tenant_id, f"oid-none-{uuid.uuid4().hex[:8]}")

    await set_tenant_context(app_session, tenant_id)
    permissions = await get_user_permissions(app_session, tenant_id, user_id)

    assert permissions == set()


async def test_permissions_are_scoped_to_the_assigning_tenant(app_session):
    tenant_a = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    tenant_b = insert_tenant("Globex", f"globex-entra-tid-{uuid.uuid4().hex[:8]}")

    user_a = insert_user(tenant_a, f"oid-a-{uuid.uuid4().hex[:8]}")
    assign_role(tenant_a, user_a, "reception_security")

    # Same permission code, but resolving it under the WRONG tenant context
    # for this user must never see the role assignment from tenant_a.
    await set_tenant_context(app_session, tenant_b)
    permissions_under_wrong_tenant = await get_user_permissions(app_session, tenant_b, user_a)
    assert permissions_under_wrong_tenant == set()
