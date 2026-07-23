"""Shared pytest fixtures for core-api.

All DB-backed tests run against the local `vms_test` database (never the
manually-bootstrapped `vms` dev database), created per the story's setup
instructions. Nothing here ever touches a real Entra ID endpoint or stores
real PII — synthetic data only (AGENTS.md).
"""

from __future__ import annotations

import pytest

from app.db.provision_roles import provision_roles

# Superuser-equivalent DSN used ONLY by test setup/teardown tooling to
# provision roles/schema on vms_test. Never used by application code and
# never the role the app or its tests connect as for actual request-path
# behavior. Same dev-only placeholder password already committed in
# docker-compose.yml.
SUPERUSER_DSN = "postgresql://vms:dev-only-not-for-real-secrets@localhost:5432/vms_test"

APP_DSN = "postgresql://vms_app:dev-only-not-for-real-secrets@localhost:5432/vms_test"
MIGRATOR_DSN = "postgresql://vms_migrator:dev-only-not-for-real-secrets@localhost:5432/vms_test"


@pytest.fixture(scope="session", autouse=True)
def _provisioned_db_roles() -> None:
    """Ensure vms_app / vms_migrator exist on vms_test before any test runs."""
    provision_roles(SUPERUSER_DSN)
