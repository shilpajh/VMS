-- Smart VMS — database role provisioning (ADR-001 §1, N3).
--
-- Two non-superuser roles, applied identically to every database this
-- service touches (dev `vms`, test `vms_test`, and any future environment):
--
--   vms_app       — the request-path role. Subject to Row-Level Security
--                    (NOBYPASSRLS). This is the ONLY role the running
--                    FastAPI application ever connects as.
--   vms_migrator  — the migration/ops role. BYPASSRLS. Used only by Alembic
--                    migrations and scripts/bootstrap_tenant.py. NEVER used
--                    on the request path.
--   vms_purge     — the US-07 retention-purge/erasure role. NOBYPASSRLS
--                    (subject to RLS+FORCE): the purge sets the per-tenant
--                    GUC and RLS structurally scopes every scrub/delete to
--                    one tenant even if a query forgets a predicate (ADR-005,
--                    SP-B2). Granted ONLY the narrow scrub/delete privileges
--                    it needs (table grants live in migration 0005). Runs the
--                    ops purge/erasure scripts; never the request path,
--                    never migrations.
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

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'vms_purge') THEN
        -- NOBYPASSRLS is the whole point: the purge is subject to RLS so the
        -- per-tenant GUC structurally scopes it (ADR-005, SP-B2).
        CREATE ROLE vms_purge LOGIN PASSWORD 'dev-only-not-for-real-secrets'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
    END IF;
END
$$;

-- Postgres 15+ no longer grants CREATE on the `public` schema to PUBLIC by
-- default, so this must be explicit per-database. vms_app only ever reads
-- schema objects created by migrations; it never creates its own.
GRANT USAGE ON SCHEMA public TO vms_app;
GRANT USAGE, CREATE ON SCHEMA public TO vms_migrator;
GRANT USAGE ON SCHEMA public TO vms_purge;  -- table-level grants: migration 0005

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

-- Day-0 bootstrap created `alembic_version` while connected as the `vms`
-- superuser (before vms_migrator existed). Hand ownership to vms_migrator
-- so it -- not the superuser -- is the role that tracks migration state
-- going forward, matching every other environment where vms_migrator runs
-- first. No-op if the table doesn't exist yet (e.g. a fresh database).
ALTER TABLE IF EXISTS alembic_version OWNER TO vms_migrator;
