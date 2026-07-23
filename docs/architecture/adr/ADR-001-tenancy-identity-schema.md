# ADR-001: Tenancy and Identity Schema (shared-schema RLS multi-tenancy, Entra ID SSO, RBAC)

## Status
Proposed

## Context
Smart VMS is a multi-tenant visitor-management SaaS (AGENTS.md, "Product and architecture"). US-10 ("SSO & roles") introduces the first real database schema; the Day-0 bootstrap deliberately created only an empty Alembic baseline (`services/core-api/alembic/versions/0000_baseline.py`) and left tenants/users/roles for this story because it has tenancy impact and must go through the full `/plan-story` pipeline rather than Quick Flow.

Constraints that shape this decision:

- **Tenant scoping is non-negotiable.** AGENTS.md ("Non-negotiable rules"): "Tenant scoping is mandatory on every query and endpoint that touches visitor/visit/credential/audit data." `.claude/rules/security-privacy.md`: "Cross-tenant access is a blocking defect in any component." `.claude/rules/database-postgresql.md`: "Every table holding tenant data carries tenant_id with an index; row-level security posture per the tenancy ADR." This ADR is that tenancy ADR — every later table's tenant posture references the pattern decided here.
- **Azure-first, Entra ID for staff auth.** AGENTS.md lists "Entra ID" and "Key Vault" in the Azure-first stack. Staff-side login is OIDC against Microsoft Entra ID. The public visitor request portal is a separate, unauthenticated surface (AGENTS.md self-protection guardrails) and its visitors are NOT modelled in this schema — this schema is for staff/tenant users only.
- **Roles must satisfy an already-published contract.** `packages/contracts/statemachine/visit-lifecycle.yaml` marks both Held-exit transitions (`Held → CheckedIn`, `Held → Denied`) with `required_permission: approve_deny_holds`. The RBAC model defined here must be able to resolve that exact permission for the reception/security role, or the state machine cannot be enforced. This ADR does not change the state machine; it makes the permission model compatible with it.
- **Portal role surface.** `.claude/rules/frontend-react.md` enumerates the web portals: public request portal (unauthenticated), host, reception/security, admin, dashboards. The minimum role taxonomy is inferred from that list plus the state-machine permission requirement (see Decision, "Inferred vs. sourced"). There is no PRD file checked into this repo; nothing here cites a PRD section.
- **Scaffold reality.** `services/core-api` runs SQLAlchemy 2 + Alembic (async `asyncpg` runtime URL, sync URL for migrations per `alembic/env.py`), FastAPI, pydantic-settings. `alembic/env.py` currently has `target_metadata = None`; wiring model metadata is an execution-phase task, not an architectural choice.

## Decision

### 1. Tenancy model: shared schema, `tenant_id` column, PostgreSQL Row-Level Security (RLS)
All tenant-owned data lives in shared tables discriminated by a `tenant_id` column, with RLS enforcing isolation at the database layer as defense-in-depth beneath the mandatory application-layer tenant check.

Rejected alternative — **schema-per-tenant / database-per-tenant**: rejected for the first cut because (a) it multiplies Alembic migration execution across N schemas and complicates the single-metadata Alembic setup already scaffolded; (b) cross-tenant reporting/dashboards (a named portal) become cross-schema joins; (c) connection-pool and Flexible Server cost scales poorly with tenant count; (d) YAGNI/modular-monolith default (AGENTS.md "Engineering philosophy"). Shared-schema + RLS gives strong isolation without that operational multiplier. If a future large/regulated tenant needs physical isolation (e.g. data-residency contract), that is a per-tenant escalation captured in a later ADR, not a reason to start with schema-per-tenant.

**RLS posture (binding for all future tenant tables):**
- Every tenant-scoped table has `tenant_id UUID NOT NULL` with an index, and `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`.
- The isolation policy is **not read-only**: it declares BOTH a `USING` clause (rows visible for SELECT/UPDATE/DELETE) AND a `WITH CHECK` clause (rows permitted on INSERT/UPDATE), so a write cannot smuggle a row into another tenant. Both clauses compare `tenant_id` to the fail-closed **single-argument** form `current_setting('app.current_tenant_id')::uuid`. The single-argument form raises if the GUC is unset — an unscoped query fails closed rather than silently seeing everything; the two-argument `current_setting(..., true)` "missing-ok" form is explicitly NOT used.
- The application connects as a non-superuser role that is subject to RLS. Migrations, the ops bootstrap script, and the US-07 purge job use a separate `BYPASSRLS` role, never the request-path role (see Consequences / execution prerequisites).
- **Request-time sequence (exact, binding):**
  1. Resolve tenant from the validated Entra token's `tid` claim via a lookup on the tenant-global `tenants` table — this lookup involves NO RLS (`tenants` is the discriminator source, not tenant-scoped).
  2. `SET LOCAL app.current_tenant_id = :tenant_id` inside the request transaction.
  3. Only then perform any scoped read (e.g. the `users` load) and, on first login, the JIT `INSERT` — which now satisfies the RLS `WITH CHECK` clause because the GUC is already set at that point.
  RLS is the backstop, not the primary control; the application check and the 403 contract (below) are the primary control.

### 2. Data model (see design-note outline for full column detail)
Owning module: **Tenant & Identity** for `tenants`, `users`, `roles`, `permissions`, `role_permissions`, `user_roles`.

- `tenants` — the tenant registry / isolation root. **Not** `tenant_id`-scoped: its own `id` *is* the tenant. Explicitly justified tenant-global. RLS not applicable (it is the discriminator source). A **reserved sentinel `platform` tenant row** (fixed, well-known UUID, seeded by the ops bootstrap script) exists so that platform-level actions have a real, non-null tenant to attribute rows to — this keeps `tenant_id NOT NULL` an absolute invariant everywhere, including on `audit_events` and on the bootstrap of `tenants` itself.
- `users` — tenant-scoped staff users. `tenant_id NOT NULL` + index. No passwords (SSO only). Stable Entra subject + issuer stored; email/display_name are PII (masked in logs). Unique `(tenant_id, external_idp_subject)`. Additionally an explicit `UNIQUE (id, tenant_id)` constraint is declared (redundant with the `id` PK, but required so that the composite FK on `user_roles` — see below — has a matching unique constraint to reference; PostgreSQL will not create the composite FK without it). `email` is NOT uniquely constrained (see Consequences / N4: Entra email is mutable and reassignable).
- `permissions` — **tenant-global** reference catalog of permission codes (e.g. `approve_deny_holds`). System-defined, identical for every tenant; extending it is a migration, not tenant data. This table is what makes `visit-lifecycle.yaml`'s `required_permission: approve_deny_holds` resolvable. Justified tenant-global (lookup table, per `/confirm-schema` §1).
- `roles` — **tenant-global** reference catalog of system roles (`tenant_admin`, `host`, `reception_security`, `dashboard_viewer`). First cut: all `is_system = true`. Justified tenant-global. Per-tenant custom roles are out of scope (see Consequences).
- `role_permissions` — **tenant-global** mapping of global roles to global permissions.
- `user_roles` — tenant-scoped assignment of a role to a user. `tenant_id NOT NULL` + index. Cross-tenant assignment is structurally prevented by a composite FK `(user_id, tenant_id) → users(id, tenant_id)`, so a `user_roles` row can never bind a user to a role under a different tenant.
- `audit_events` — append-only audit sink. Owned by the **Audit & Reporting** module, introduced here (first schema) because identity/tenancy actions must produce durable audit evidence from day one. Tenant-scoped (`tenant_id NOT NULL` + index); platform-level `tenant.created` is attributed to the reserved sentinel `platform` tenant row, so there is no nullable tenant marker anywhere. Written to by many modules by design (this is an intentional shared sink, not a module-boundary blur — pre-declared here so the `/confirm-schema` §5 graph check does not misread it). Full partitioning/retention/reporting schema is a later Audit & Reporting story; US-10 introduces only the append-only core it needs. This audit table is NOT itself subject to the user-PII purge (see Security and privacy impact).

### 3. RBAC model and state-machine compatibility
Effective permissions of a user = union of permissions of the roles assigned to that user, resolved `user_roles → roles → role_permissions → permissions`. The domain layer's Held-exit authorization check calls `has_permission(user, tenant, "approve_deny_holds")`, which resolves true for the `reception_security` role. This is the compatibility guarantee required by `visit-lifecycle.yaml`.

First-cut role → permission seed (system roles):
- `tenant_admin` → `manage_users`, `manage_roles`, `view_dashboards` (tenant administration; user/role management).
- `host` → `approve_deny_visits` (approve/deny visit requests — the `Requested → Registered` / `Requested → Denied` host transitions).
- `reception_security` → `approve_deny_holds` (the privileged Held-exit permission), `checkin_confirm`.
- `dashboard_viewer` → `view_dashboards`.

The RBAC catalog (the `role_permissions` seed) carries a **permission policy version** string, bumped whenever the seed changes (a migration). This version is recorded on role-assignment audit events, mirroring the `policy_version` field the visit state machine already records on transitions.

### 4. Tenant bootstrap (ops script, no code surface) — resolves former O1
There is **no cross-tenant "platform operator" role and no cross-tenant API endpoint** in this story's scope; `POST /platform/tenants` does not exist. A tenant and its first `tenant_admin` user row are inserted directly by an **internal ops/seed script** during customer onboarding, run with the `BYPASSRLS` migration role — never through the API. The same ops script seeds the reserved sentinel `platform` tenant row (fixed UUID) used for platform-level audit attribution. This removes the chicken-and-egg bootstrap problem without introducing a cross-tenant isolation exception into the running application.

### 5. SSO / Entra ID integration point
- **Protocol:** OIDC Authorization Code + PKCE. Staff portals (React SPA, MSAL) authenticate against Entra ID directly and obtain tokens from Entra; core-api validates the bearer JWT statelessly. **Token storage is in-memory only** (JS runtime memory) — never `localStorage` or `sessionStorage` — with short-lived access tokens and MSAL-managed refresh; this is a stated decision, not a deferred option (`.claude/rules/frontend-react.md` already forbids tokens/PII in localStorage). A server-side BFF/callback is explicitly NOT used for the first cut.
- **Token validation (concrete checks, all required):** verify signature via **per-issuer JWKS discovery with key rotation** (not a pinned static key); verify `exp`/`nbf`; pin `aud` to this API's Entra **App ID / App ID URI** and reject tokens minted for any other resource; resolve the token's `tid`/issuer to exactly one Smart VMS `tenants` row and verify the token `tid` claim **equals that tenant's stored `entra_tenant_id`** (not merely "issuer is well-formed"). A token whose issuer/`tid` maps to no tenant, to a suspended tenant, or whose `tid` does not match the stored value → 401.
- **User mapping / JIT provisioning:** the token's `oid` claim is the **canonical** `external_idp_subject` (it is immutable and non-reassignable within an Entra tenant). `sub` is used only as a fallback when `oid` is absent (rare, e.g. certain token configurations), and the two are never mixed for the same user without de-duplication, because mixing `oid` and `sub` as the subject key risks creating duplicate `users` rows for one person. On first successful login with no matching `users(tenant_id, external_idp_subject)`, the user is JIT-provisioned **with zero roles** (least privilege) — an authenticated identity with no access until a `tenant_admin` explicitly assigns a role.
- Secrets (client IDs/secrets, signing config) live in Key Vault / managed identity only, never in code, config files, or logs.

### Inferred vs. sourced (explicit)
- **Sourced from repo files:** the `approve_deny_holds` permission and Held-exit privilege requirement (`visit-lifecycle.yaml`); the portal list host/reception-security/admin/dashboards and the no-tokens-in-localStorage rule (`.claude/rules/frontend-react.md`); Entra ID + Key Vault + PostgreSQL Flexible Server (`AGENTS.md`); tenant_id-and-index / RLS / rollback requirements (`.claude/rules/database-postgresql.md`, `backend-python.md`); the 403-on-tenant-scope error contract (`.claude/rules/contracts.md`).
- **Inferred (no PRD in repo):** the specific role names (`tenant_admin`, `host`, `reception_security`, `dashboard_viewer`) and their exact permission bundles beyond `approve_deny_holds`; JIT-with-zero-roles default; the permission policy version mechanism. These are design proposals for Gate 1 approval, not PRD-cited requirements.

## Consequences

**Benefits**
- Single migration path, single metadata, simple pooling — fits the scaffolded async SQLAlchemy/Alembic setup and the modular-monolith default.
- Two independent isolation layers (application tenant check + FORCE RLS with USING and WITH CHECK): a missed application-layer filter still cannot leak or write across tenants at the DB layer.
- Cross-tenant dashboards/reporting are ordinary filtered queries, not cross-schema joins.
- The RBAC catalog being tenant-global keeps the state-machine permission contract identical across all tenants — `approve_deny_holds` means the same thing everywhere.
- No cross-tenant runtime endpoint or role exists (bootstrap is ops-script only), so there is no in-app tenant-isolation exception to defend.

**Limitations / deliberately out of scope for the first cut**
- **Per-tenant custom roles** — first cut ships fixed system roles only. Extensibility path (non-breaking): add nullable `tenant_id` to `roles`/`role_permissions` where NULL = system role; captured in a future ADR when needed.
- **Group-claim → role auto-mapping** and **SCIM provisioning** — deferred; assignment is explicit admin action.
- **Entra B2B / guest staff** — first cut supports **native members of the customer's own Entra tenant only**; B2B/guest subject mapping is deferred to a future story (was open question O3, now scoped out — not left open).
- **Site-scoped roles** — roles are tenant-wide in the first cut; there is no `sites` table yet. Scoping a role to specific sites is a future extension.
- **Service/machine identities & API keys** — out of scope; the C# edge connector authenticates via outbound-only mTLS (AGENTS.md), a separate mechanism.
- **MFA / conditional access** — delegated to Entra ID policy, not modelled here.
- **Local/password auth** — never; SSO-only by decision.

**Operational impact**
- **Separate migration DB role/URL is an execution-phase prerequisite, not optional (N3):** execution must provision a `BYPASSRLS` migration/ops role and a distinct connection URL for it, separate from the app's `settings.database_url` (which uses the non-superuser RLS-subject role). The ops bootstrap/seed script and the US-07 purge job run under the `BYPASSRLS` role.
- `alembic/env.py` must be wired to model metadata during execution (currently `target_metadata = None`).
- **Staff-PII retention (placeholder, pending real compliance sign-off — not final policy):** disabled/departed users are purged **180 days after disable**; the append-only `audit_events` trail is preserved separately and is NOT subject to this user purge. Azure resources default to the **India region**. This retention window and residency default are a working placeholder to unblock the schema; they must be confirmed by real DPDP compliance sign-off before GA, and this caveat must not be dropped. These identity stores enter the US-07 retention/purge scope; the purge emits audit evidence (`.claude/rules/database-postgresql.md`).
- Vendor lock-in: Entra-specific claims (`tid`, `oid`) are read at the auth adapter boundary only; the rest of the domain sees a normalized `(tenant_id, user_id, permissions[])` principal, keeping the IdP replaceable in principle.

## Security and privacy impact
- **Tenant isolation:** enforced twice — mandatory application tenant check before DB access, plus FORCE RLS (USING + WITH CHECK, fail-closed single-argument GUC) keyed on `app.current_tenant_id`. Composite FK `(user_id, tenant_id)` makes a cross-tenant role assignment structurally impossible. Any cross-tenant read/write is a Blocking defect (`.claude/rules/security-privacy.md`).
- **403 contract:** any tenant-scoped endpoint returns 403 when the authenticated principal's tenant does not match the path/resource tenant (`.claude/rules/contracts.md`), before RLS is relied upon.
- **Stateless-token revocation gap, explicitly handled (S5):** because Entra access tokens are stateless and un-revoked until expiry, disabled-user status and tenant-suspension status are **re-checked on every request** against the current DB state, not trusted from token-mint time. Any Redis-cached principal/permission data is **invalidated immediately** on role assign/revoke and on user-disable, and that Redis cache is in scope for the same erasure/purge workflow (US-07) as the PostgreSQL rows — not just Postgres.
- **Least privilege:** JIT-provisioned users start with zero roles; access is only ever granted by an explicit, audited `tenant_admin` action. No cross-tenant runtime role exists.
- **PII handling:** `users.email` and `display_name` are PII; never logged (`AGENTS.md`, `security-privacy.md`). No passwords, no Aadhaar, no biometric data in this schema. No visitor PII here — this table is staff-only. Token storage is in-memory only on the SPA side (never localStorage/sessionStorage).
- **Secrets:** all Entra client/signing secrets in Key Vault / managed identity; never in code, fixtures, prompts, or logs.
- **Audit (5-field shape, per B2):** every `tenant.created`, `user.provisioned`, `user.enabled`, `user.disabled`, `role.assigned`, and `role.revoked` emits an append-only audit event carrying the same field shape the visit state machine requires — **actor, timestamp, policy_version, reason, correlation_id** — plus a target reference (target_type/target_id) identifying the affected user/tenant. `policy_version` is the permission-policy version for role changes. The `actor` is defined explicitly for edge cases: for JIT self-provisioning the actor is the newly-provisioned user themself (self-provision); for `tenant.created` (ops-script bootstrap, no human platform operator per §4) the actor is a fixed reserved **"system" actor marker** attributed to the sentinel `platform` tenant. Audit rows are never UPDATEd/DELETEd and are not subject to the user-PII purge.
- **Consent:** out of scope for this schema (staff SSO, not visitor consent); visitor consent versioning is a separate visitor-domain concern (`security-privacy.md`) — flagged so it is not assumed covered here.
- **Offline behavior:** not applicable — staff SSO is an online cloud-side flow; the C# edge connector's offline authorization is a separate concern and out of scope for this ADR.

### Open questions surfaced to the orchestrator/human (not silently resolved)
- **O2 — Ownership/timing of `audit_events`.** This ADR introduces the append-only audit core under the Audit & Reporting module now, so identity events have a durable home. Confirm with the Audit & Reporting owner that US-10 introduces it (vs. a dedicated audit story), and that the shared-sink write pattern (many modules append) is accepted.

*(Former O1 tenant-bootstrap, O3 Entra B2B/guest, O4 auth pattern, and O5 staff-PII retention/residency are now DECIDED and folded into the Decision and Consequences sections above; they are no longer open.)*
