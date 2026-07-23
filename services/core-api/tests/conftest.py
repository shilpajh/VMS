"""Shared pytest fixtures for core-api.

All DB-backed tests run against the local `vms_test` database (never the
manually-bootstrapped `vms` dev database), created per the story's setup
instructions. Nothing here ever touches a real Entra ID endpoint or stores
real PII — synthetic data only (AGENTS.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

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
