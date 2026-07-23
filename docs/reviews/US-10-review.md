# US-10 (SSO & roles) — /verify-story Review

**Track 1 — Compliance/Security (security-privacy-reviewer, independent, read-only)**
**Branch:** `feature/US-10`. **Scope:** compliance/security pass against `docs/plans/US-10.md` and `docs/architecture/adr/ADR-001-tenancy-identity-schema.md`.

**Graph note:** `graphify-out/graph.json` does not exist (confirmed). Expected — US-10 is the first domain code, so there is no graph to query for blast radius. `/graph-query` was not runnable; blast-radius was traced by hand from the diff. This matches the loop self-report's own carry-forward item #2. The next story touching `users`/`user_roles`/`audit_events` must run `/graph-query` before its diff-only review.

**Scope check:** the committed diff maps cleanly to the plan's Part C file map. No cross-tenant HTTP route exists (only `identity.py`'s router + `/health`; grep for `@app.`/`APIRouter` confirms nothing else). No `POST /platform/tenants`. `bootstrap_tenant.py` is a `__main__`/`-m` script with no router import, unreachable via HTTP. Migration `WITH CHECK` present (line 103), `audit_events` grants are `SELECT, INSERT` only — no UPDATE/DELETE (line 267), JIT provisioning creates users with zero roles (no default assignment anywhere). All correct as the ADR promised. One out-of-plan artifact found (untracked test — see Should-fix).

---

## BLOCKING

### B1 — Entra token validation trusts the token's self-asserted `iss` claim as its own trust anchor, enabling token forgery and full cross-tenant impersonation.

File: `services/core-api/app/auth/entra.py`, `EntraTokenValidator.validate()` lines 122–137, in concert with `HttpJWKSProvider._fetch_jwks()` lines 93–102 and `app/auth/dependencies.py` lines 82–107.

The validator reads the unverified `iss` claim from the incoming token (line 123: `issuer = unverified_claims.get("iss")`), then fetches the signing keys **from that same attacker-controllable URL** (`HttpJWKSProvider.get_public_key(issuer, kid)` → `_fetch_jwks` → `httpx.get(f"{issuer.rstrip('/')}/discovery/v2.0/keys")`, line 96), and finally calls `jwt.decode(..., issuer=issuer, ...)` (line 136) — which only checks that the token's `iss` equals itself, a tautology. There is no allowlist restricting the issuer to a Microsoft Entra authority, and no check that the issuer corresponds to the `tid` (e.g. that `iss == https://login.microsoftonline.com/{tid}/v2.0`). Config has no allowed-issuer/authority setting (`app/config.py` has only `entra_api_audience`).

Consequence: an attacker who hosts their own JWKS document at any HTTPS URL and signs a JWT with their own RSA key can mint a token with `iss = https://attacker.example`, any `tid`, any `oid`, and `aud = api://smart-vms-core-api-...`. The validator fetches the attacker's public key from the attacker's URL, the signature verifies, `aud` matches (the audience is a published App ID URI, not a secret), and `issuer == issuer` passes. `app/auth/dependencies.py` then resolves the tenant purely by `Tenant.entra_tenant_id == claims.tid` (line 84) — the attacker sets `tid` to any victim tenant's `entra_tenant_id` — and resolves the user by `(tenant_id, external_idp_subject)` (lines 101–107). By setting `oid` to a known victim admin's object id, the attacker is authenticated **as that admin with the admin's full permission set**; with an arbitrary `oid` they are JIT-provisioned into the victim tenant. The `tid`-equals-stored-`entra_tenant_id` check does not mitigate this, because `tid` is attacker-chosen and non-secret; the only thing that could establish the token genuinely came from Entra — fetching keys from a *trusted* Microsoft endpoint — is exactly what is missing.

This is a complete authentication bypass and cross-tenant impersonation vector shipping in the production wiring (`get_token_validator()` in `dependencies.py` line 60 uses `HttpJWKSProvider`). It violates AGENTS.md "Non-negotiable rules" / AuthN ("Staff authenticate via Entra ID OIDC" — the token must actually be proven to originate from Entra), and `.claude/rules/security-privacy.md` ("Cross-tenant access is a blocking defect in any component"). ADR-001 §5's own words — "resolve the token's `tid`/issuer to exactly one tenant and verify the token `tid` claim equals that tenant's stored `entra_tenant_id` (not merely 'issuer is well-formed')" — are not satisfied: the issuer is neither pinned to a trusted authority nor bound to the `tid`.

Suggested remediation (not a patch — for the owning engineer): derive the expected issuer from a trusted source rather than the token, e.g. pin the authority to `https://login.microsoftonline.com/{tid}/v2.0` (or a per-tenant stored `expected_issuer`) and only fetch JWKS from that Microsoft-hosted, TLS-validated endpoint; reject any token whose `iss` is not the expected Microsoft authority for the resolved tenant. Add an explicit test that a validly-signed token from an unexpected/attacker issuer is rejected (the current suite in `test_entra_auth.py` only tests an *unknown key*, never a *forged issuer with a known-to-itself key* — the exact gap that let this pass).

Note: this is a code-correctness security defect and is within the reviewer's scope to block on directly (not a biometric/vendor/privacy-policy decision requiring separate human sign-off).

---

## SHOULD FIX

- `services/core-api/tests/test_tenant_isolation_cross_tenant_writes.py` is **untracked** (`git status` shows `??`), not committed on `feature/US-10`. Its own header says it is a "/verify-story gap fill" closing the fact that the committed suite exercised only *one* cross-tenant scenario (`GET .../users → 403`) while the plan promises 403 on every one of the six `/tenants/{id}/...` routes including writes. This is valuable coverage that will not run in CI and will not survive the merge unless committed. Commit it (and confirm it passes) or the write-side tenant-isolation guarantee has no executable verifier.
- Retention/erasure (checklist item 9 / `database-postgresql.md` "Retention/purge jobs must cover every new store added"): `users` now holds PII (`email`, `display_name`) with **no purge-workflow registration** — deferred to a not-yet-existing US-07. The 180-day/India-region policy is an explicit placeholder pending real DPDP compliance sign-off (ADR-001 Consequences; loop-state carry-forward #1). This cannot be closed inside US-10 (no workflow to register with) and requires a **human compliance owner**. It must be tracked as a hard GA gate, not lost.
- `app/auth/dependencies.py:95` and `tests/conftest.py:159` build `SET LOCAL app.current_tenant_id = '{...}'` by f-string interpolation. Safe by provenance (a DB-sourced UUID object) today, but prefer `SELECT set_config('app.current_tenant_id', :tid, true)` with a bind parameter so the safety doesn't depend on every future caller passing a trusted UUID. Already flagged by the builder; low risk, worth hardening.

## NOTES

- Audit `correlation_id` is a fresh `uuid.uuid4()` per event (`api/identity.py`, `dependencies.py:130`) rather than a request-scoped id, so multiple events from one request (e.g. JIT-provision + a later action) can't be correlated. Meets the 5-field contract; consider a request-level correlation id later.
- `GET /roles` and `GET /permissions` require only authentication, no specific permission — a JIT zero-role user can read the full RBAC taxonomy. Low sensitivity (system-defined global catalog); consistent with the plan.
- Committed default DSNs in `app/config.py` carry `dev-only-not-for-real-secrets` placeholder passwords (matching docker-compose). Clearly labeled, env-overridable via pydantic-settings; not a real secret. `entra_api_audience` and the frontend `PLACEHOLDER_*` values (`apps/web/src/auth/msal.ts`) are likewise obvious placeholders. No real secrets found in code/fixtures/logs.
- PII/logging hygiene verified clean: no `logging`/`logger`/`print` of `email`/`display_name` in the auth/identity path (only `provision_roles.py:37` prints `__doc__`); audit `actor` uses `external_idp_subject`/`system`, never email; `MeResponse` omits email; no DTO serializes `external_idp_subject` or raw claims. `TokenValidationError` messages never include the token/claims.
- Frontend storage hygiene verified: `cacheLocation: 'memoryStorage'` (`msal.ts:24`); no `localStorage.setItem`/`sessionStorage.setItem` anywhere under `apps/web/src` (only assertions in `msal.test.ts`). JIT zero-role UX cliff handled distinctly from error state (`App.tsx:57-66`).
- Request-time sequence (verify item 1) traced and correct: `get_current_principal` is a route dependency, shares the single `get_session` transaction (FastAPI dependency caching), sets the GUC at line 95 **before** any `users`/`user_roles`/`audit_events` access; `get_session` commits once at request end so `SET LOCAL` stays in scope. Fail-closed single-arg `current_setting`, `FORCE`+`ENABLE` RLS, `vms_app` = NOBYPASSRLS, and append-only grants all confirmed in the migration source (not just comments). These parts of the loop self-report hold up.

**Escalation:** B1 is a blocking authentication defect and must return to Execution (security-remediation loop, max 2 cycles). The retention/DPDP item requires a human compliance owner and cannot be resolved by an agent.

Relevant files:
- `/home/shilpa/SmartVMS/services/core-api/app/auth/entra.py`
- `/home/shilpa/SmartVMS/services/core-api/app/auth/dependencies.py`
- `/home/shilpa/SmartVMS/services/core-api/app/config.py`
- `/home/shilpa/SmartVMS/services/core-api/tests/test_entra_auth.py`
- `/home/shilpa/SmartVMS/services/core-api/tests/test_tenant_isolation_cross_tenant_writes.py` (untracked)
- `/home/shilpa/SmartVMS/services/core-api/alembic/versions/0001_tenancy_identity.py`

---

## Track 2 — Broader test suite (qa-automation-engineer)

*Pending — running in parallel, will be appended when it lands.*
