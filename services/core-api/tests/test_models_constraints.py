"""Task 2 (US-10): SQLAlchemy model constraint tests.

These exercise the models' DB-level constraints directly via
`Base.metadata.create_all` in a disposable scratch schema — NOT via the real
Alembic migration (that's task 3, tested separately in
tests/test_migration.py against the actual `public` schema). This isolates
"are the constraints declared correctly" from "does the migration apply
them", per the plan's task ordering.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Permission, Role, RolePermission, Tenant, User, UserRole
from app.models.base import Base
from tests.conftest import MIGRATOR_DSN

SCRATCH_SCHEMA = "test_models_constraints"


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(MIGRATOR_DSN, future=True)
    with eng.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{SCRATCH_SCHEMA}"'))
        conn.execute(text(f'SET search_path TO "{SCRATCH_SCHEMA}"'))
        Base.metadata.create_all(conn)
    try:
        yield eng
    finally:
        with eng.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE'))
        eng.dispose()


@pytest.fixture()
def session(engine):
    with engine.connect() as conn:
        conn.execute(text(f'SET search_path TO "{SCRATCH_SCHEMA}"'))
        with Session(bind=conn) as sess:
            yield sess
            sess.rollback()


def _make_tenant(session: Session, entra_tenant_id: str) -> Tenant:
    tenant = Tenant(name="Acme", entra_tenant_id=entra_tenant_id)
    session.add(tenant)
    session.flush()
    return tenant


def test_users_unique_tenant_external_idp_subject(session: Session) -> None:
    tenant = _make_tenant(session, "acme-entra-tid-1")
    session.add(
        User(
            tenant_id=tenant.id,
            external_idp_subject="oid-1",
            email="a@example.com",
            display_name="A",
        )
    )
    session.flush()
    session.add(
        User(
            tenant_id=tenant.id,
            external_idp_subject="oid-1",
            email="b@example.com",
            display_name="B",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_users_same_external_idp_subject_different_tenant_is_allowed(session: Session) -> None:
    tenant_a = _make_tenant(session, "acme-entra-tid-2")
    tenant_b = _make_tenant(session, "globex-entra-tid-2")
    session.add(
        User(
            tenant_id=tenant_a.id,
            external_idp_subject="oid-shared",
            email="a@example.com",
            display_name="A",
        )
    )
    session.add(
        User(
            tenant_id=tenant_b.id,
            external_idp_subject="oid-shared",
            email="b@example.com",
            display_name="B",
        )
    )
    session.flush()  # must not raise


def test_user_roles_composite_fk_rejects_mismatched_tenant(session: Session) -> None:
    tenant_a = _make_tenant(session, "acme-entra-tid-3")
    tenant_b = _make_tenant(session, "globex-entra-tid-3")
    user_a = User(
        tenant_id=tenant_a.id,
        external_idp_subject="oid-a",
        email="a@example.com",
        display_name="A",
    )
    session.add(user_a)
    session.flush()

    role = Role(code=f"role-{uuid.uuid4().hex[:8]}", name="Test Role")
    session.add(role)
    session.flush()

    # user_a belongs to tenant_a; attempt to assign a role under tenant_b's
    # tenant_id (mismatched pair) -- must be rejected by the composite FK
    # (user_id, tenant_id) -> users(id, tenant_id), since no users row has
    # (user_a.id, tenant_b.id).
    session.add(UserRole(tenant_id=tenant_b.id, user_id=user_a.id, role_id=role.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_user_roles_composite_fk_accepts_matching_tenant(session: Session) -> None:
    tenant = _make_tenant(session, "acme-entra-tid-4")
    user = User(
        tenant_id=tenant.id,
        external_idp_subject="oid-match",
        email="a@example.com",
        display_name="A",
    )
    session.add(user)
    session.flush()

    role = Role(code=f"role-{uuid.uuid4().hex[:8]}", name="Test Role")
    session.add(role)
    session.flush()

    session.add(UserRole(tenant_id=tenant.id, user_id=user.id, role_id=role.id))
    session.flush()  # must not raise


def test_role_code_is_unique(session: Session) -> None:
    session.add(Role(code="dup-role", name="First"))
    session.flush()
    session.add(Role(code="dup-role", name="Second"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_permission_code_is_unique(session: Session) -> None:
    session.add(Permission(code="dup-permission", description="first"))
    session.flush()
    session.add(Permission(code="dup-permission", description="second"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_role_permissions_composite_pk_rejects_duplicate(session: Session) -> None:
    role = Role(code=f"role-{uuid.uuid4().hex[:8]}", name="Test Role")
    permission = Permission(code=f"perm-{uuid.uuid4().hex[:8]}", description="d")
    session.add_all([role, permission])
    session.flush()
    session.add(RolePermission(role_id=role.id, permission_id=permission.id, policy_version="v1"))
    session.flush()
    session.add(RolePermission(role_id=role.id, permission_id=permission.id, policy_version="v1"))
    with pytest.raises(IntegrityError):
        session.flush()
