from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Request-path connection: the non-superuser, RLS-subject `vms_app` role
    # (ADR-001 §1). The running application NEVER connects as the `vms`
    # superuser or as `vms_migrator` — only migrations/ops scripts do.
    database_url: str = "postgresql+asyncpg://vms_app:dev-only-not-for-real-secrets@localhost:5432/vms"
    # Migration/ops connection: the separate BYPASSRLS `vms_migrator` role
    # (ADR-001 §1/N3), used only by Alembic and scripts/bootstrap_tenant.py —
    # never the request path. Sync driver (psycopg2), per alembic/env.py.
    migrations_database_url: str = (
        "postgresql://vms_migrator:dev-only-not-for-real-secrets@localhost:5432/vms"
    )
    redis_url: str = "redis://localhost:6379/0"

    # This API's Entra App ID / App ID URI. Bearer tokens whose `aud` claim
    # doesn't exactly match this are rejected (ADR-001 §5) -- placeholder
    # for local dev, never a real Entra registration; production value comes
    # from Key Vault / app configuration, never checked in.
    entra_api_audience: str = "api://smart-vms-core-api-dev-placeholder"


settings = Settings()
