---
name: bootstrap-environment
description: One-time Day-0 setup of the Smart VMS repo skeleton, local dev environment (Postgres/Redis via Docker), and tooling for backend (Python/FastAPI), frontend (React/TS), and kiosk (Flutter). Sets up EMPTY scaffolding and Alembic wiring only — it does NOT create the tenants/users/roles schema, since that has tenancy impact and must go through the normal plan pipeline (/plan-story US-10), never skipped as Quick Flow.
argument-hint: "(no arguments — run once, at repo root, before Story 1)"
disable-model-invocation: true
---

# Environment bootstrap (run once, before any story)

This is infrastructure setup, not a feature — it has no PRD acceptance criteria and produces no user-facing behavior, so it does not go through /plan-story or the human gates. It is still bounded and reviewed like any other change (open a PR, get it merged normally) — it just isn't a "story."

## 0. Token-efficiency tooling (one-time, before anything else)
Install RTK (rtk-ai/rtk) — a transparent CLI proxy that compresses command *output* (git, test runners, linters, docker) before it reaches the agent's context, 60-90% smaller on common commands, <10ms overhead:
```
brew install rtk          # or: curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
rtk init -g                # installs the Claude Code PreToolUse hook
```
Install caveman (JuliusBrussee/caveman) — compresses agent *reply* tokens by ~65%, terse-not-lossy:
```
curl -fsSL https://raw.githubusercontent.com/JuliusBrussee/caveman/main/install.sh | bash
```
Restart Claude Code after both. From then on, `git status`, `pytest`, `cargo test`, etc. are automatically rewritten to their `rtk` equivalents — no change needed to any skill's instructions, since the hook rewrites the command transparently before execution. Scope note: this only covers Bash tool calls (git/test/lint/docker/etc.) — it does not touch `Read`/`Grep`/`Glob`, which is what `/graph-query` is for. The two are complementary, not overlapping. Caveman's boundary — where terse is fine, where it never is — is defined in AGENTS.md's Communication style section; do not apply it to anything a human reads for sign-off.

## 1. Repo skeleton
Create, if not already present:
```
services/core-api/           # Python FastAPI backend
services/workers/            # background workers (outbox consumers)
apps/web/                    # React + TypeScript web portals
apps/kiosk/                  # Flutter kiosk + muster app
apps/edge-connector/         # C#/.NET edge connector (Phase 2 — scaffold only, no logic yet)
packages/contracts/          # already exists: statemachine/, openapi/, asyncapi/
infra/                       # Terraform/Bicep (Phase 2+ — placeholder folder + README for now)
docs/plans/ docs/loops/ docs/deploys/ docs/poc/   # created empty with a .gitkeep
```

## 2. Backend (Python/FastAPI)
```
services/core-api/pyproject.toml   # Python 3.12+, fastapi, uvicorn, pydantic>=2, sqlalchemy>=2, alembic, pytest, httpx
services/core-api/app/main.py      # bare FastAPI app + GET /health returning {"status": "ok"}
services/core-api/app/config.py    # settings from env vars (DATABASE_URL, REDIS_URL) via pydantic-settings
services/core-api/alembic.ini + alembic/env.py   # `alembic init` wiring, pointed at config.DATABASE_URL
services/core-api/alembic/versions/0000_baseline.py   # an EMPTY migration (no tables) — confirms the migration
                                                        # pipeline works end to end before any real schema exists
services/core-api/tests/test_health.py   # one smoke test: GET /health returns 200
```
Do NOT create a tenants, users, visits, or any domain table here. The first real migration is US-10's, produced by the normal pipeline below.

## 3. Frontend (React + TypeScript)
```
apps/web/package.json       # vite (or next), react, typescript strict, @tanstack/react-query, i18next, vitest
apps/web/.env.example       # VITE_API_BASE_URL=http://localhost:8000
apps/web/src/App.tsx        # placeholder shell that calls GET /health and renders the result — proves the
                             # frontend-to-backend wire works before any real screen exists
```

## 4. Kiosk (Flutter) — scaffold only
```
flutter create apps/kiosk
```
Leave default counter-app content; it gets replaced story by story (US-01 onward). Do not build check-in UI here.

## 5. Local dev environment
```
docker-compose.yml   # postgres:16 (POSTGRES_DB=vms, POSTGRES_USER=vms, POSTGRES_PASSWORD=dev-only-not-for-real-secrets)
                      # redis:7
.env.example          # DATABASE_URL=postgresql://vms:dev-only-not-for-real-secrets@localhost:5432/vms
                      # REDIS_URL=redis://localhost:6379/0
```
Run `docker compose up -d`, then `alembic upgrade head` (applies only the empty 0000_baseline migration), then start core-api and confirm `GET /health` returns 200, and apps/web's placeholder screen shows it.

## 6. What this skill deliberately does NOT do
- Does not create any table with tenant_id, visitor data, credentials, or audit records — that's US-10's job via the real pipeline (tenancy impact = never Quick Flow, per AGENTS.md's Quick Flow threshold).
- Does not stand up the C# edge connector logic, Azure infra, Key Vault, or CI/CD pipeline gates — those are separate, later setup items (see the pre-flight checklist in README.md).
- Does not seed any data, fixture, or secret beyond a clearly-marked local-dev-only Postgres password.

## Exit
Confirm: `docker compose up -d` works, `alembic upgrade head` applies cleanly, `GET /health` returns 200 from core-api, apps/web renders the health-check result, `flutter run` launches the default kiosk scaffold. Commit this as a normal PR (not a "story"). Then immediately run:
```
/plan-story US-10   # SSO & roles — the first REAL migration (tenants, users, roles) happens here
```
