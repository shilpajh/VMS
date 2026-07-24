"""Pydantic v2 DTOs for the Tenant & Identity API surface (US-10, task 8).

Explicit DTOs at every boundary (backend-python.md): NONE of these ever
serialize `external_idp_subject` or any raw token claim -- only normalized,
tenant-scoped fields a tenant_admin is entitled to see about their own
tenant.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class MeResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    display_name: str
    roles: list[str]
    permissions: list[str]


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    description: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    display_name: str
    status: str


class UserCreateRequest(BaseModel):
    """Admin-initiated pre-provisioning (e.g. admin already knows the
    person's Entra object id) -- distinct from JIT provisioning on first
    SSO login, which this schema also supports via the same
    (tenant_id, external_idp_subject) uniqueness."""

    external_idp_subject: str = Field(min_length=1)
    email: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class UserUpdateRequest(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")
    reason: str = Field(min_length=1)


class UserRoleOut(BaseModel):
    role_id: uuid.UUID
    role_code: str


class RoleAssignRequest(BaseModel):
    role_id: uuid.UUID
    reason: str = Field(min_length=1)
