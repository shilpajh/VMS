"""Shared pytest fixtures for core-api.

All DB-backed tests run against the local `vms_test` database (never the
manually-bootstrapped `vms` dev database), created per the story's setup
instructions. Nothing here ever touches a real Entra ID endpoint or stores
real PII — synthetic data only (AGENTS.md).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.provision_roles import provision_roles

CORE_API_ROOT = Path(__file__).resolve().parents[1]

# Superuser-equivalent DSN used ONLY by test setup/teardown tooling to
# provision roles/schema on vms_test. Never used by application code and
# never the role the app or its tests connect as for actual request-path
# behavior. Same dev-only placeholder password already committed in
# docker-compose.yml.
SUPERUSER_DSN = "postgresql://vms:dev-only-not-for-real-secrets@localhost:5432/vms_test"

# Points at Postgres' always-present maintenance DB -- needed to CREATE/DROP
# disposable scratch databases (e.g. tests/test_migration.py), which cannot
# be done while connected to the database being created/dropped.
SUPERUSER_MAINTENANCE_DSN = "postgresql://vms:dev-only-not-for-real-secrets@localhost:5432/postgres"

APP_DSN = "postgresql://vms_app:dev-only-not-for-real-secrets@localhost:5432/vms_test"
MIGRATOR_DSN = "postgresql://vms_migrator:dev-only-not-for-real-secrets@localhost:5432/vms_test"

# Async (asyncpg) variants for the app's real runtime session layer.
APP_ASYNC_DSN = "postgresql+asyncpg://vms_app:dev-only-not-for-real-secrets@localhost:5432/vms_test"
MIGRATOR_ASYNC_DSN = (
    "postgresql+asyncpg://vms_migrator:dev-only-not-for-real-secrets@localhost:5432/vms_test"
)


@pytest.fixture(scope="session", autouse=True)
def _provisioned_db_roles() -> None:
    """Ensure vms_app / vms_migrator exist on vms_test before any test runs."""
    provision_roles(SUPERUSER_DSN)


def alembic_config(sqlalchemy_url: str) -> Config:
    cfg = Config(str(CORE_API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(CORE_API_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema(_provisioned_db_roles) -> None:
    """Bring vms_test to `alembic head` before any test that expects the
    Tenant & Identity tables to exist. Runs as vms_migrator (BYPASSRLS),
    exactly like a real deployment would (ADR-001 §1/N3) -- never as the
    `vms` superuser or `vms_app`.

    tests/test_migration.py exercises upgrade/downgrade mechanics itself
    against fully disposable scratch databases, so it never interferes with
    this shared vms_test schema.
    """
    command.upgrade(alembic_config(MIGRATOR_DSN), "head")


# --- Async session fixture for tests exercising the real request-path DB
# layer (app.auth.dependencies, app.domain.rbac), always as vms_app against
# vms_test -- never settings.database_url's default (which points at the
# dev `vms` database).
_test_app_engine = create_async_engine(APP_ASYNC_DSN, poolclass=NullPool)
TestAppSessionLocal = async_sessionmaker(_test_app_engine, expire_on_commit=False)

# --- Async session as the vms_purge role (US-07): NOBYPASSRLS, so RLS+FORCE
# structurally scopes the purge to whichever tenant the GUC is set to. The
# purge tests use THIS, never app_session/migrator, so they exercise the real
# structural-isolation guarantee (SP-B2), not a bypass.
PURGE_ASYNC_DSN = "postgresql+asyncpg://vms_purge:dev-only-not-for-real-secrets@localhost:5432/vms_test"
_test_purge_engine = create_async_engine(PURGE_ASYNC_DSN, poolclass=NullPool)
TestPurgeSessionLocal = async_sessionmaker(_test_purge_engine, expire_on_commit=False)


@pytest.fixture()
async def app_session(_migrated_schema):
    """Mirrors app.db.session.get_session's one-transaction-per-request
    shape: everything a test does through this fixture shares one
    transaction, so a `SET LOCAL app.current_tenant_id` set via
    get_current_principal stays valid for the rest of the test -- exactly
    like it does for the rest of a real request."""
    async with TestAppSessionLocal() as session:
        yield session
        await session.rollback()


# --- Synchronous BYPASSRLS helpers for seeding fixture data across tenants
# (mirrors what an ops script / another tenant's admin would do), reused by
# multiple test modules.
def insert_tenant(name: str, entra_tenant_id: str, status: str = "active") -> uuid.UUID:
    tenant_id = uuid.uuid4()
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (id, name, entra_tenant_id, status) VALUES (%s, %s, %s, %s)",
                (str(tenant_id), name, entra_tenant_id, status),
            )
    finally:
        conn.close()
    return tenant_id


def insert_user(
    tenant_id: uuid.UUID,
    external_idp_subject: str,
    email: str | None = None,
    display_name: str | None = None,
    status: str = "active",
) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users "
                "(id, tenant_id, external_idp_subject, email, display_name, status) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    str(user_id),
                    str(tenant_id),
                    external_idp_subject,
                    email or f"{external_idp_subject}@example.com",
                    display_name or external_idp_subject,
                    status,
                ),
            )
    finally:
        conn.close()
    return user_id


def set_user_status(user_id: uuid.UUID, status: str) -> None:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET status = %s WHERE id = %s", (status, str(user_id)))
    finally:
        conn.close()


async def set_tenant_context(session, tenant_id: uuid.UUID) -> None:
    """Test helper mirroring step 2 of ADR-001 §1's request sequence, for
    tests that exercise RLS-scoped queries directly (not through
    get_current_principal). tenant_id is always a UUID object we generated
    ourselves in test setup, never raw user input."""
    from sqlalchemy import text

    await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))


class AlwaysAllowRateLimiter:
    """Test-only stand-in for app.security.rate_limit.TokenBucketRateLimiter,
    used to override get_per_ip_rate_limiter/get_per_tenant_rate_limiter in
    portal test modules that are not themselves testing rate-limiting
    (tests/test_portal_rate_limit.py exercises the real Redis-backed
    limiter directly) -- avoids every portal test in the whole suite
    sharing one Redis-backed per-IP bucket keyed on TestClient's fixed
    "testclient" host, which would otherwise make later tests flaky/failing
    once the shared bucket empties."""

    async def check(self, key: str, *, now: float | None = None) -> bool:
        return True


def assign_role(tenant_id: uuid.UUID, user_id: uuid.UUID, role_code: str) -> None:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM roles WHERE code = %s", (role_code,))
            (role_id,) = cur.fetchone()
            cur.execute(
                "INSERT INTO user_roles (id, tenant_id, user_id, role_id) VALUES (%s, %s, %s, %s)",
                (str(uuid.uuid4()), str(tenant_id), str(user_id), str(role_id)),
            )
    finally:
        conn.close()
