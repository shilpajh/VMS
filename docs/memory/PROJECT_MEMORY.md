# Smart VMS — Project Memory

Append-only log, one entry per completed story, written by `/document-story` (see step 3).
Future stories' GATHER step reads the last 5-10 entries here before touching anything else —
this is the cheapest context a story can get, cheaper than re-reading old specs or diffs.
Keep entries to 6-10 lines each; a rambling entry defeats the purpose.

<!-- Entries below this line, most recent last. -->

## US-10 — SSO & roles (2026-07-24)
Built: first real schema (`tenants`/`users`/`roles`/`permissions`/`role_permissions`/`user_roles`/`audit_events`, ADR-001's RLS/tenancy pattern); Entra ID OIDC validation + JIT provisioning + RBAC; `/me`/`/roles`/`/permissions`/tenant-scoped user/role-management routes; MSAL staff SSO wiring (in-memory token cache only).
Key decisions: ADR-001 (RLS `ENABLE`+`FORCE`, fail-closed `current_setting`, composite-FK cross-tenant prevention — now the reused pattern for every later tenant-scoped table). `SET LOCAL app.current_tenant_id` via f-string interpolation of a DB-sourced UUID — safe by provenance but flagged for future bind-param hardening (still open).
Gotchas: a real Blocking auth-bypass (B1) — `EntraTokenValidator` trusted the token's self-asserted `iss` as its own trust anchor (fetched JWKS from an attacker-controllable URL), enabling full cross-tenant impersonation. Fixed by pinning the expected issuer to the DB-stored `tenants.entra_tenant_id`, independently re-verified. Also: the plan's mandated `packages/contracts/openapi/identity.yaml` was initially skipped entirely and only caught at `/verify-story` — contract-file deliverables need their own explicit execute-story task checkbox, not just a file-map mention.
Depends on/blocks: first story, no dependency. Blocks every later story needing auth/RBAC/tenancy (US-11 already stacked on this). B1 fix is a hard release/merge gate for both `feature/US-10` and any stacked branch until Human Gate 2 signs off.
Files: `services/core-api/app/auth/entra.py`, `app/auth/dependencies.py`, `docs/architecture/adr/ADR-001-tenancy-identity-schema.md`, `docs/reviews/US-10-review.md`.
