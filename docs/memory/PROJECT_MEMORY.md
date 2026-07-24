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

## US-11 — Website pre-registration visibility (2026-07-24)
Built: tenant-scoped `visits`+`outbox_messages` tables; public unauthenticated portal submission (rate-limited + Turnstile CAPTCHA); host approve/deny issuing check-in codes via transactional outbox; `view_visits` RBAC permission; full audit coverage. First visit-lifecycle transitions implemented (`Requested→{Registered,Denied}`).
Key decisions: ADR-002 (outbox + envelope encryption); check-in code = `token_urlsafe(24)`+SHA-256; retention (90d/7d) and consent framework are explicit placeholders pending human DPDP sign-off.
Gotchas: scope-creep incident — portal-UI commits landed post-Gate-1/post-first-verify-story, undetected until a later re-run; resolved via retroactive plan amendment + one-time design-gate review (see proposed skill change, not yet applied, in this story's PR). Real dedup cross-actor info-disclosure bug found and fixed mid-loop. Turnstile CAPTCHA-verify runs before rate-limiting (vendor call uncapped by our own limiter) — Should-fix, not blocking.
Depends on/blocks: stacked on `feature/US-10` (B1 fix independently verified fixed; both branches await Human Gate 2 release sign-off). Unblocks: relay-worker story, host-approval UI story, NULL-host reception triage.
Files: `services/core-api/app/api/portal.py`, `app/domain/visits/service.py`, `docs/architecture/adr/ADR-002-transactional-outbox-notification-contract.md`, `docs/reviews/US-11-review.md`.

## US-01 — Pre-registered check-in, QR (hardware-free) (2026-07-24)
Built: wired `Registered→CheckedIn` for the QR path only (no face/biometric); `POST /visits/checkin` (`checkin_confirm`-gated) with a guarded UPDATE folding hash+tenant+status+expiry into one `WHERE` clause; credential-grant + host-arrival-notify outbox messages, both envelope-encrypted (ADR-003); minimal authenticated `CheckinPage`.
Key decisions: ADR-003 establishes the device-command envelope (no `zone` field — `site_id`/`device_id` reserved-null instead — kept out of a contract future badge/door commands reuse verbatim); credential `expiry` reuses the arrival-deadline as a known-wrong placeholder, flagged as an open question, not fixed.
Gotchas: (1) plan invented a redundant `checkin_visits` permission — `checkin_confirm` already existed from US-10's baseline seed; caught mid-`/execute-story`, not at plan time, because nothing checks existing seeded permissions before proposing a new one. (2) `POST /visits/checkin` had to be registered *before* `GET /visits/{visit_id}` in the router, or Starlette resolves the method mismatch to a 405 from the wrong route instead of falling through. (3) A guard's time-window/expiry check folded into the SAME guarded `UPDATE`'s `WHERE` clause (not a separate post-check step) closes a timing/behavior oracle two independent design reviews caught from different angles. All three proposed as rule/skill changes in this story's PR, not just logged here.
Depends on/blocks: stacked on US-10 (RBAC)/US-11 (visits/outbox schema). `watchlist_clear` is a stub and `Registered→Held` is unwired — blocks any release claiming automated watchlist coverage. Unblocks US-04 (host arrival actions — same arrival-notify pattern) and any future device-command contract (ADR-003 is now the reference pattern, same role ADR-001/ADR-002 played).
Files: `services/core-api/app/domain/visits/service.py` (`checkin_visit`), `app/domain/visits/guards.py`, `docs/architecture/adr/ADR-003-credential-grant-command-contract.md`, `docs/reviews/US-01-review.md`.
