"""RBAC resolution (US-10, ADR-001 §3).

Effective permissions of a user = union of permissions of the roles
assigned to that user, resolved `user_roles -> roles -> role_permissions ->
permissions`. Resolved directly from the DB on every call -- no Redis or
in-process caching (ADR-001 §5/S5: immediate DB resolution is the chosen
approach for this cut; a cached principal would also need invalidation on
every role assign/revoke/user-disable, which this story does not build).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Permission, Role, RolePermission, UserRole

# Bumped whenever the role_permissions seed changes (a migration). Recorded
# on role-assignment audit events (ADR-001 §3).
PERMISSION_POLICY_VERSION = "v1"


async def get_user_permissions(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> set[str]:
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.tenant_id == tenant_id, UserRole.user_id == user_id)
    )
    result = await session.execute(stmt)
    return {row[0] for row in result.all()}


async def get_user_role_codes(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> set[str]:
    stmt = (
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.tenant_id == tenant_id, UserRole.user_id == user_id)
    )
    result = await session.execute(stmt)
    return {row[0] for row in result.all()}


async def has_permission(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, permission_code: str
) -> bool:
    permissions = await get_user_permissions(session, tenant_id, user_id)
    return permission_code in permissions
