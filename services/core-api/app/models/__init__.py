"""SQLAlchemy 2 models for the Tenant & Identity module (US-10, ADR-001 §2).

Importing this package registers every table on `Base.metadata` — required
both for `alembic/env.py`'s `target_metadata` wiring and for any test that
needs the full schema (e.g. `Base.metadata.create_all`).
"""

from app.models.audit import AuditEvent
from app.models.base import Base
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.tenant import PLATFORM_TENANT_ENTRA_TENANT_ID, PLATFORM_TENANT_ID, Tenant
from app.models.user import User

__all__ = [
    "Base",
    "Tenant",
    "PLATFORM_TENANT_ID",
    "PLATFORM_TENANT_ENTRA_TENANT_ID",
    "User",
    "Role",
    "Permission",
    "RolePermission",
    "UserRole",
    "AuditEvent",
]
