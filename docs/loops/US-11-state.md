# US-11 — execute-story loop state

## Iteration 1 (single pass, all 13 tasks completed — no re-iteration needed)

Builder agent, commits `36dfcac`..`6b9dd2c` on `feature/US-11` (stacked on `feature/US-10`).

### Test results — independently re-run and confirmed
`183 passed, 1 failed, 1 skipped`. The one failure/skip is the **pre-existing US-10 gap** (missing `packages/contracts/openapi/identity.yaml`, flagged in `docs/reviews/US-10-review.md`) — unrelated to US-11, unchanged by this work, not a regression. US-11 added **109 new tests**, all passing. Baseline before this story: 76 tests (74 passed/1 failed/1 skipped).

### Final `/confirm-schema` pass — live-verified against the dev DB (not just unit tests)

Applied `0002_visits_and_outbox` to the dev `vms` database myself (the builder's tests ran against `vms_test`/scratch DBs only) and re-ran the checklist live:

**1. Tenancy — PASS**
- `visits`, `outbox_messages`: `tenant_id NOT NULL` + index, confirmed live (`relrowsecurity`/`relforcerowsecurity` both `t` on both tables).
- `tenants.public_slug`: correctly left tenant-global (no RLS) — `tenants` is the discriminator source, consistent with ADR-001.
- Composite FK `(host_user_id, tenant_id) → users(id, tenant_id)`: structurally sound under Postgres MATCH SIMPLE (NULL exempts the row; non-NULL enforces same-tenant).

**2. State-machine alignment — PASS**
`visits.status` CHECK constraint carries the full `visit-lifecycle.yaml` enum (not just the three states this story writes), avoiding migration churn for later stories. Only `Requested→{Registered,Denied}` are wired to endpoints in this cut, matching the plan's scope fence.

**3. Audit and compliance — PASS, with the same flagged deferral as US-10**
- Grants confirmed live: `vms_app` has exactly `SELECT, INSERT, UPDATE` on both `visits` and `outbox_messages` — no `DELETE`.
- `visit.denied`'s audit `reason` is a coded value (`VISIT_DENIED_REASON_CODE`), not the host's free-text `denial_reason` — confirmed in `app/domain/visits/service.py`. This was the specific PII-into-purge-exempt-audit fix from the design review; verified it actually landed, not just claimed.
- Retention/purge for `visits`/`outbox_messages` PII is still a placeholder (90-day/7-day, per the human decision), not an implemented purge job — same carry-forward status as US-10's `users` table, tracked as a GA gate.

**4. Migration mechanics — PASS**
`downgrade()` tested both as an isolated step and as part of a full `head→base` teardown (existing `test_migration.py` was extended since a second migration now exists on the chain). Idempotent seed inserts (`ON CONFLICT DO NOTHING` pattern, consistent with `0001`).

**5. Architecture-boundary check — NOT RUNNABLE (same as US-10, flagged not skipped)**
`graphify-out/graph.json` still doesn't exist. ADR-002 pre-declares the `visits→outbox_messages` and `visits→audit_events` edges as intentional shared-boundary writes so a future graph check doesn't misread them as a module blur.

### Carry-forward items for `/verify-story`
1. **US-10's B1 auth-bypass finding is still open** — this remains a hard merge/ship gate for both `feature/US-10` and `feature/US-11`. US-11's forged-token test (`test_visits_forged_token_cross_tenant.py`, 8 tests covering forged-signature and trusted-signature-wrong-tenant cases against all three authenticated endpoints) proves US-11's own endpoints correctly reject a forged/wrong-tenant principal under the *current* (pre-fix) `get_current_principal` — this is not a claim that B1 itself is resolved.
2. **`CHECKIN_CODE_VALIDITY` (7 days)** — the builder picked this as a placeholder; no duration was specified anywhere in the plan/ADR-002 beyond "`not_valid_after` is populated." This is a product decision, not an engineering one — flagging for confirmation, not silently accepted as final.
3. **`policy_version` on `visit.registered`/`visit.denied` audit events** — the builder used the *live* `PERMISSION_POLICY_VERSION` constant (which evaluates to `"v2"` after this story's own RBAC bump) rather than a hardcoded `"v1"`. Reasoned justification: a hardcoded value would go stale the moment the RBAC seed changes within the same story. This reads as correct engineering judgment, not an unresolved ambiguity — noting it here for `/verify-story`'s awareness, not as an open question.
4. **Idempotency-Key dedup mechanics**: implemented as a `submission_dedup_key` column on `visits` (unique per `(tenant_id, dedup_key)`) rather than a separate table — the plan specified the *property* (tenant-scoped, content-hashed) but not this mechanic. Reasonable interpretation; worth a security-review glance at `/verify-story` given it's new dedup-as-security-boundary logic.
5. **File count (44) exceeds the plan's own flagged guardrail proximity** — the plan's Risk section anticipated being "close to" execute-story's 25-file ceiling; the actual count is meaningfully higher. Flagged for Gate 2's attention as an accepted trade-off, not a silent overrun.
6. **Process note:** task 9 (portal endpoint) was not built in strict red-then-green test-first order, unlike every other task in this story. The builder reported this itself rather than claiming uniform TDD discipline — noting it here so `/verify-story` can weigh in if it matters for this story's rigor bar.

### Standing invariants — spot-checked independently, all hold
- Tenant scoping: RLS `ENABLE`+`FORCE` confirmed live on both new tables; the public (unauthenticated) path resolves tenant via `resolve_public_tenant` before any scoped DB access, mirroring the authenticated-path pattern.
- No automated denial: N/A (no biometric/watchlist path in this story).
- Audit on every high-risk action: `visit.requested`/`visit.registered`/`visit.denied` all confirmed present with the 5-field shape; PII-in-audit fix (item 3 above) confirmed landed.
- No PII/secrets in logs: covered by `test_visits_never_log_and_send_gate.py`; not independently re-verified beyond that test in this pass.
- Async boundary: no synchronous vendor call in the approval request — the outbox write is the transition boundary, confirmed in `app/domain/visits/service.py`.

**Result: no unresolved Blocking items from execution itself. Carry-forward items above (US-10's B1 merge gate, two placeholder decisions, one implementation interpretation, file-count size, one process note) — none are silent, all explicitly tracked. Ready for `/verify-story`.**
