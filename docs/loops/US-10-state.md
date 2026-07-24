# US-10 — execute-story loop state

## Iteration 1 (single pass, all tasks completed — no re-iteration needed)

### Tasks 1–11 (backend) — builder agent, commits `201c8cf`..`ab71780` on `feature/US-10`
All 11 tasks done test-first. 65/65 backend tests passing (independently re-run and confirmed).

### Task 12 (frontend MSAL wiring) — builder agent, commit `f6f450b` on `feature/US-10`
Done. 8/8 frontend tests passing, `tsc -b`/`vite build`/`oxlint` all clean (independently re-run and confirmed).

### Task 13 — final `/confirm-schema` pass (this record)

Applied the `.claude/skills/confirm-schema/SKILL.md` checklist across all seven tables introduced by `alembic/versions/0001_tenancy_identity.py` (`tenants`, `users`, `roles`, `permissions`, `role_permissions`, `user_roles`, `audit_events`). Verified live against the running dev Postgres (`docker compose exec postgres psql`), not just via the unit test suite.

**1. Tenancy — PASS**
- `users`, `user_roles`, `audit_events`: `tenant_id NOT NULL` + index, confirmed via `\dt`/migration read and live RLS check.
- `tenants`, `roles`, `permissions`, `role_permissions`: explicitly justified tenant-global (`tenants` is the discriminator root; the other three are system-wide reference catalogs) — stated in the migration's own comments, not left silent.
- FK boundary: `user_roles`' composite FK `(user_id, tenant_id) → users(id, tenant_id)` structurally prevents cross-tenant role assignment — confirmed present in the migration (line 213-217) and exercised by `tests/test_models_constraints.py`.

**2. State-machine alignment — N/A**
No visit-status column in this migration; `users.status`/`tenants.status` are unrelated lifecycle fields (active/disabled, active/suspended) with their own `CHECK` constraints, not `visit-lifecycle.yaml` states.

**3. Audit and compliance — PASS, with one flagged deferral**
- Append-only confirmed **live**: `information_schema.role_table_grants` for `vms_app` on `audit_events` shows only `INSERT`/`SELECT` — no `UPDATE`/`DELETE` grant exists at the DB layer (not just app-layer discipline).
- **Retention/purge (US-07) registration is explicitly deferred, not silently skipped** — ADR-001's Consequences section states the 180-day post-disable window as a placeholder pending real compliance sign-off, and the actual purge-job registration is out of this story's file map. **Carrying this forward as a required follow-up for `/verify-story` and for whoever picks up US-07** — a table nobody remembers to purge is a DPDP gap per AGENTS.md, so this must not be dropped.
- No biometric/raw-identity columns exist in this schema (staff-only, no visitor data) — confirmed by inspection, N/A is correct here.

**4. Migration mechanics — PASS**
- `downgrade()` implemented and exercised (upgrade → downgrade → re-upgrade tested live against disposable scratch databases per the builder agent's test suite, `tests/test_migration.py`).
- Seed inserts use `ON CONFLICT ... DO NOTHING` — idempotent against re-run.
- No destructive change / no backfill needed (net-new schema, no prior data).

**5. Architecture-boundary check — NOT RUNNABLE (flagged, not skipped)**
`graphify-out/graph.json` does not exist yet — expected, since no domain code existed before this story (US-10 is the first real schema). The module-boundary graph check from `/confirm-schema` §5 cannot run against a graph that doesn't exist. **Non-blocking for this story** (there is nothing to compare against yet), but flagged so the next story that touches `users`/`roles`/`audit_events` runs `/graph-query` before its own diff-only review, per the confirm-schema skill's own instruction.

### Carry-forward items for `/verify-story`
1. US-07 retention/purge registration for the six identity tables + `audit_events` — currently a stated placeholder (180 days, India region), not implemented or compliance-signed-off.
2. `graphify-out/graph.json` doesn't exist — first-schema graph check deferred, re-run on the next story touching these tables.
3. Backend agent's own flagged items (see its report): `SET LOCAL` string-interpolation of a DB-sourced UUID (safe by provenance, worth a second look), no Python lint/typecheck tooling exists yet in the scaffold, `POST /tenants/{id}/users` semantics are inferred (no PRD to check against).

### Standing invariants — spot-checked independently, all hold
- Tenant scoping: RLS `ENABLE`+`FORCE` confirmed live on all three tenant tables (`relrowsecurity`/`relforcerowsecurity` both `t`).
- Fail-closed: querying `users` as `vms_app` with the GUC unset raises `unrecognized configuration parameter "app.current_tenant_id"` — confirmed live, not just in a unit test.
- No automated denial: N/A (no biometric/watchlist path in this schema).
- Audit on every high-risk action: confirmed via `tests/test_audit_events.py` (backend agent) — 5-field shape present.
- No PII/secrets in logs: not independently re-verified beyond code review in this pass; carried into `/verify-story`'s scope.

**Result: no unresolved Blocking items. Two Should-track deferrals (US-07 registration, graph re-check) carried forward explicitly. Ready for `/verify-story`.**
