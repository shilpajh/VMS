-- Smart VMS — database role provisioning (ADR-001 §1, N3).
--
-- Two non-superuser roles, applied identically to every database this
-- service touches (dev `vms`, test `vms_test`, and any future environment):
--
--   vms_app       — the request-path role. Subject to Row-Level Security
--                    (NOBYPASSRLS). This is the ONLY role the running
--                    FastAPI application ever connects as.
--   vms_migrator  — the migration/ops role. BYPASSRLS. Used only by Alembic
--                    migrations, scripts/bootstrap_tenant.py, and the future
--                    US-07 retention/purge job. NEVER used on the request
--                    path.
--
-- Passwords here are the same dev-only placeholder already committed in
-- docker-compose.yml for the `vms` superuser — not a real secret, and never
-- used outside local development. Production credentials come from Key
-- Vault / managed identity (AGENTS.md), never from this file.
--
-- Idempotent: safe to re-run against a database that already has these
-- roles (e.g. because roles are cluster-wide in Postgres, not per-database).

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'vms_app') THEN
        CREATE ROLE vms_app LOGIN PASSWORD 'dev-only-not-for-real-secrets'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'vms_migrator') THEN
        CREATE ROLE vms_migrator LOGIN PASSWORD 'dev-only-not-for-real-secrets'
            NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS NOREPLICATION;
    END IF;
END
$$;

-- Postgres 15+ no longer grants CREATE on the `public` schema to PUBLIC by
-- default, so this must be explicit per-database. vms_app only ever reads
-- schema objects created by migrations; it never creates its own.
GRANT USAGE ON SCHEMA public TO vms_app;
GRANT USAGE, CREATE ON SCHEMA public TO vms_migrator;

-- vms_migrator also needs CREATE on the database itself (not just the
-- public schema) so that test fixtures can create/drop disposable scratch
-- schemas without needing superuser. `GRANT ... ON DATABASE` requires a
-- literal identifier, so this is done dynamically against whichever
-- database roles.sql is applied to.
DO $$
BEGIN
    EXECUTE format('GRANT CREATE ON DATABASE %I TO vms_migrator', current_database());
END
$$;
