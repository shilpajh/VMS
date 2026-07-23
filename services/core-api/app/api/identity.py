"""Tenant & Identity API routes (US-10, task 8).

Every tenant-scoped route returns 403 on a tenant mismatch (never 404, so a
cross-tenant caller can never distinguish "wrong tenant" from "no such
resource under the resolved tenant" -- contracts.md, ADR-001 §2).

Deliberately absent: any `POST /platform/tenants` or other cross-tenant
route. Tenant creation is ops-script only (ADR-001 §4, task 11) -- there is
no code path here that could create one.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dtos.identity import (
    MeResponse,
    PermissionOut,
    RoleAssignRequest,
    RoleOut,
    UserCreateRequest,
    UserOut,
    UserRoleOut,
    UserUpdateRequest,
)
from app.auth.dependencies import Principal, get_current_principal
from app.db.session import get_session
from app.domain.audit import write_audit_event
from app.domain.rbac import (
    PERMISSION_POLICY_VERSION,
    get_user_role_codes,
    has_permission,
)
from app.models import Permission, Role, User, UserRole

router = APIRouter()


def _require_tenant_match(principal: Principal, tenant_id: uuid.UUID) -> None:
    if principal.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")


async def _require_permission(
    session: AsyncSession, principal: Principal, permission_code: str
) -> None:
    if not await has_permission(session, principal.tenant_id, principal.user_id, permission_code):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


@router.get("/me", response_model=MeResponse)
async def get_me(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> MeResponse:
    user = (await session.execute(select(User).where(User.id == principal.user_id))).scalar_one()
    roles = await get_user_role_codes(session, principal.tenant_id, principal.user_id)
    return MeResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        display_name=user.display_name,
        roles=sorted(roles),
        permissions=sorted(principal.permissions),
    )


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[Role]:
    result = await session.execute(select(Role))
    return list(result.scalars().all())


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[Permission]:
    result = await session.execute(select(Permission))
    return list(result.scalars().all())


@router.get("/tenants/{tenant_id}/users", response_model=list[UserOut])
async def list_tenant_users(
    tenant_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[User]:
    _require_tenant_match(principal, tenant_id)
    await _require_permission(session, principal, "manage_users")
    result = await session.execute(select(User).where(User.tenant_id == tenant_id))
    return list(result.scalars().all())


@router.post(
    "/tenants/{tenant_id}/users", response_model=UserOut, status_code=status.HTTP_201_CREATED
)
async def create_tenant_user(
    tenant_id: uuid.UUID,
    body: UserCreateRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> User:
    _require_tenant_match(principal, tenant_id)
    await _require_permission(session, principal, "manage_users")

    user = User(
        tenant_id=tenant_id,
        external_idp_subject=body.external_idp_subject,
        email=body.email,
        display_name=body.display_name,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="user already exists for this tenant"
        ) from None

    await write_audit_event(
        session,
        tenant_id=tenant_id,
        event_type="user.provisioned",
        actor=principal.external_idp_subject,
        target_type="user",
        target_id=user.id,
        reason="admin_provisioned",
        correlation_id=uuid.uuid4(),
    )
    return user


@router.patch("/tenants/{tenant_id}/users/{user_id}", response_model=UserOut)
async def update_tenant_user(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> User:
    _require_tenant_match(principal, tenant_id)
    await _require_permission(session, principal, "manage_users")

    user = (
        await session.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    previous_status = user.status
    user.status = body.status
    await session.flush()

    if previous_status != body.status:
        event_type = "user.enabled" if body.status == "active" else "user.disabled"
        await write_audit_event(
            session,
            tenant_id=tenant_id,
            event_type=event_type,
            actor=principal.external_idp_subject,
            target_type="user",
            target_id=user.id,
            reason=body.reason,
            correlation_id=uuid.uuid4(),
        )
    return user


@router.get("/tenants/{tenant_id}/users/{user_id}/roles", response_model=list[UserRoleOut])
async def list_user_roles(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> list[UserRoleOut]:
    _require_tenant_match(principal, tenant_id)
    await _require_permission(session, principal, "manage_roles")

    stmt = (
        select(UserRole.role_id, Role.code)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.tenant_id == tenant_id, UserRole.user_id == user_id)
    )
    result = await session.execute(stmt)
    return [UserRoleOut(role_id=row[0], role_code=row[1]) for row in result.all()]


@router.post(
    "/tenants/{tenant_id}/users/{user_id}/roles",
    response_model=UserRoleOut,
    status_code=status.HTTP_201_CREATED,
)
async def assign_user_role(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    body: RoleAssignRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> UserRoleOut:
    _require_tenant_match(principal, tenant_id)
    await _require_permission(session, principal, "manage_roles")

    role = (
        await session.execute(select(Role).where(Role.id == body.role_id))
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="role not found")

    target_user = (
        await session.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    assignment = UserRole(tenant_id=tenant_id, user_id=user_id, role_id=role.id)
    session.add(assignment)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="role already assigned"
        ) from None

    await write_audit_event(
        session,
        tenant_id=tenant_id,
        event_type="role.assigned",
        actor=principal.external_idp_subject,
        target_type="user",
        target_id=user_id,
        reason=body.reason,
        correlation_id=uuid.uuid4(),
        policy_version=PERMISSION_POLICY_VERSION,
    )
    return UserRoleOut(role_id=role.id, role_code=role.code)


@router.delete(
    "/tenants/{tenant_id}/users/{user_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_user_role(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    reason: str = "revoked_by_admin",
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_tenant_match(principal, tenant_id)
    await _require_permission(session, principal, "manage_roles")

    assignment = (
        await session.execute(
            select(UserRole).where(
                UserRole.tenant_id == tenant_id,
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
            )
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="role assignment not found")

    await session.delete(assignment)
    await session.flush()

    await write_audit_event(
        session,
        tenant_id=tenant_id,
        event_type="role.revoked",
        actor=principal.external_idp_subject,
        target_type="user",
        target_id=user_id,
        reason=reason,
        correlation_id=uuid.uuid4(),
        policy_version=PERMISSION_POLICY_VERSION,
    )
