# US-11 (Website pre-registration visibility) — Design-Gate Review

**Reviewer:** security-privacy-reviewer (independent, read-only). **Scope:** pre-implementation design-gate cold-read of the domain-architect design note (not yet written to disk as an ADR at review time). "Blocking" = the design as specified would produce a blocking defect if implemented as-is — same standard as the ADR-001 review.

Overall: a strong, unusually self-flagging design note. The rate-limiting/CAPTCHA specification, state-machine enforcement, anti-enumeration posture, and audit-actor reconciliation are all at or above the bar. One Blocking item — about what US-11 is allowed to ship on top of, not a flaw in US-11's own logic — plus ten Should-fix specification gaps to close before implementation.

---

## BLOCKING

### B1 — US-11's host-side tenant isolation rests entirely on `get_current_principal`, which currently contains US-10's open, unremediated auth-bypass (US-10 review B1). The design's §0 framing ("doesn't depend on the fix") is correct for development sequencing but incorrect as a merge/ship decision.

The design note's §0 states US-11 "doesn't depend on US-10's auth-bypass fix ... but can be built/tested locally regardless of that unrelated bug." The first half is defensible for development — US-11 can be written and unit-tested against a local principal. The second half mislabels US-10 B1 an "unrelated bug": US-11's host approve/deny/list endpoints derive both the ownership check (`visit.host_user_id == principal.user_id`) and the RLS `SET LOCAL app.current_tenant_id` entirely from `get_current_principal`. Per the still-open US-10 finding (`docs/reviews/US-10-review.md`), that function trusts the token's self-asserted `iss` as its own trust anchor, allowing a forged token with an attacker-chosen `tid`/`oid` to authenticate as any host in any tenant.

If US-11 is implemented and merged as §0 sequences it, every US-11 host endpoint inherits full cross-tenant impersonation: forged principals could approve/deny visits (issue or withhold credentials) or list another tenant's visitors, because the `principal.tenant_id` feeding the RLS GUC is attacker-controlled. RLS does not save this — it enforces the GUC value, and the GUC value is itself forged. This is `.claude/rules/security-privacy.md`'s "cross-tenant access is a blocking defect in any component," now reachable through the new US-11 surface.

**Required corrections before this design is approved:**
1. Reclassify the US-10 B1 fix as a hard **merge/ship gate** for US-11 — build and unit-test on the branch is fine; merging to a release branch or deploying while B1 is open is not.
2. US-11's verifier set must include a forged-issuer, wrong-`tid` cross-tenant test fired at US-11's own `/visits/{id}/approve`, `/deny`, and `GET /visits` endpoints specifically (not only reusing US-10's identity-route tests) — the isolation guarantee for the new surface must be proven, not assumed by inheritance.

---

## SHOULD FIX

1. **Public `Idempotency-Key` dedup scope is unspecified and is a cross-tenant/cross-visitor disclosure risk if implemented naively.** The design specifies the *outbox* idempotency key precisely but leaves the anonymous *public-submission* dedup key unscoped. Require: the dedup entry is written/read only after `SET LOCAL app.current_tenant_id` (tenant-scoped), and keyed to submission content (e.g. a hash of `contact_value`+`host_hint`) so a guessed key can't return an unrelated submission's reference.
2. **Host-typed `denial_reason` free text is piped verbatim into the purge-exempt `audit_events.reason`.** `audit_events` is append-only and explicitly not subject to user-PII purge. A host's free-text deny reason can contain visitor PII, writing it into a forever-retained store while the same text also lives on the purgeable `visits.denial_reason` column — defeating erasure. Prefer: `visit.denied`'s audit `reason` carries a coded/controlled value or a reference to `visits.id`; the free-text reason stays only on the purgeable `visits` row.
3. **New PII stores (`visits`, `outbox_messages`) have no retention/purge-workflow registration.** Same gap already flagged for US-10's `users` table. Cannot be closed inside US-11 (US-07 doesn't exist yet); requires a human compliance owner; must be tracked as a hard GA gate, not lost.
4. **`checkin_code_hash` under-specifies the code as a credential.** Neither entropy/format nor hash algorithm is specified. If it's a short numeric OTP, a bare hash is weak against offline brute force (needs a keyed HMAC + attempt-limiting + short expiry); if it's a long `secrets.token_urlsafe`, a plain hash is fine. State the entropy + hashing decision now even though verification is a later story.
5. **Plaintext check-in code + visitor PII sit at rest in `outbox_messages.payload` JSONB**, protected only by RLS + disk encryption. Recommend application-level envelope encryption (Key Vault-managed key) for the payload. Two adjacent gaps: (a) failed/never-dispatched rows hold plaintext code + PII indefinitely — define a max-age purge, register with #3; (b) the relay worker must never log the payload on retry/error.
6. **Gherkin Scenario 5's expected 409 doesn't map cleanly onto the design's endpoint surface.** The design's safety property (no route accepts a target status/trigger) means an attempt to reach `CheckedIn` has no route at all — likely 404/405/422, not 409. The design's real 409 path is "approve/deny on a non-Requested visit." Define the exact HTTP call the verifier makes for Scenario 5 before implementation.
7. **The deferred `view_visits` model must be confirmed against Scenario 1's "live visitor list" assertion.** Owner-scoped-only visibility satisfies Scenario 1 only if the verifier queries as the owning host. This is a real authZ scope decision the design correctly declines to make alone.
8. **Consent/privacy-notice for visitor PII collection is a real DPDP gap**, correctly flagged by the design, not resolvable by an agent — needs the Compliance-module owner + a human sign-off, tracked as a GA-blocking item.
9. **Migration rollback not mentioned.** `0002_visits` (and `outbox_messages` if same migration) must ship a tested `downgrade()`.
10. **Notification message lacks a staleness/expiry send-gate.** `code_expires_at` is carried in the payload but nothing states the worker honors it before dispatching. Define a "do not dispatch if expired/superseded" guard as part of the recommended ADR-002.

## NOTES

- Rate-limiting/CAPTCHA design genuinely satisfies the AGENTS.md portal guardrail — concrete numbers, concrete mechanism, correct ordering (verify before DB work), correct `X-Forwarded-For` handling. Two refinements only: order CAPTCHA-verify before tenant-slug resolution (avoid a slug-validity timing oracle); state the `siteverify` secret lives in Key Vault.
- State-machine enforcement (domain table + DB-level guarded conditional UPDATE + CHECK backstop) exceeds the bar — genuinely race-safe, domain-layer-plus-DB-transaction as AGENTS.md requires.
- Audit-actor "portal"/stable-id resolution: agreed, matches the enforced US-10 precedent. The only PII-into-audit problem is the *reason* free-text (Should-fix #2), not the actor.
- Composite nullable FK `(host_user_id, tenant_id) → users(id, tenant_id)`: structurally sound under Postgres MATCH SIMPLE — NULL exempts the row, non-NULL always enforces same-tenant.
- `tracking_reference` scheme is a good anti-volume-oracle now (no public lookup endpoint exists in this story, so no probe surface). Flag forward: a future lookup-by-reference story should revisit entropy and add rate-limiting.
- Orphaned NULL-host visits are invisible-but-retained under the current design — ensure the retention/purge registration (#3) explicitly covers these.
- Integration relay worker's tenant context is unspecified (fine to defer, not built here) — needs its own security review when built; must not run as the request-path `vms_app` role.

**Disposition:** One Blocking merge-gate finding (must not ship while US-10 B1 is open; must add US-11-specific forged-token tests). Ten Should-fix items, two of which (#3 purge registration, #8 consent) require a human compliance owner. Design is otherwise sound and approvable once the §0 framing is corrected and the Should-fix gaps are closed.

Relevant files:
- `/home/shilpa/SmartVMS/specs/features/US-11-portal-visibility.feature`
- `/home/shilpa/SmartVMS/docs/reviews/US-10-review.md` (the open B1 dependency)
- `/home/shilpa/SmartVMS/docs/architecture/adr/ADR-001-tenancy-identity-schema.md`
- `/home/shilpa/SmartVMS/services/core-api/app/domain/audit.py`, `/home/shilpa/SmartVMS/services/core-api/app/models/audit.py`
- `/home/shilpa/SmartVMS/services/core-api/app/models/user.py` (`uq_users_id_tenant_id`)
- `.claude/rules/security-privacy.md`, `.claude/rules/database-postgresql.md`, `.claude/rules/backend-python.md`, `.claude/rules/contracts.md`

---

# /verify-story — Track 1: Compliance/Security (post-implementation)

**Reviewer:** security-privacy-reviewer (independent, read-only). **Branch:** `feature/US-11` (stacked on `feature/US-10`). **Scope:** post-implementation pass before Human Gate 2. Diff cold-read against the plan's file map and both ADRs — no scope creep found; the two additions not named verbatim in the file map (`submission_dedup_key` column, `enforce_public_rate_limits` helper) are in-scope mechanics for approved tasks 7/9. `graphify-out/graph.json` still doesn't exist — architecture-boundary check remains not-runnable, expected.

## BLOCKING

### B1 (carried forward, NOT resolved in US-11 — hard merge/ship gate, correctly preserved not dropped)
US-11's three authenticated host endpoints (`app/api/visits.py` lines 62-67, 87-91, 113) all derive their RLS tenant scoping and host-ownership check from `get_current_principal`, which still carries US-10's open auth-bypass (US-10 review B1) — a forged token with an attacker-chosen `tid`/`oid` authenticates as any host in any tenant; RLS enforces a GUC value that is itself forged.

**Precise status of the US-11-specific forged-token test** (`tests/test_visits_forged_token_cross_tenant.py`, read in full): rigorous and satisfies the Definition of Done, but proves isolation only *given a sound validator* (it overrides with `StaticJWKSProvider`, which doesn't carry the self-asserted-issuer defect). It does NOT and cannot prove B1 itself is fixed — the residual risk sits entirely in the shared `get_current_principal`/`HttpJWKSProvider`, covered only by the merge gate. **Neither `feature/US-10` nor `feature/US-11` may merge to a release branch or deploy until US-10 B1 is remediated.** This is the sole hard blocker for shipping; not a defect in US-11's own code.

## SHOULD FIX

1. **Content-hash submission dedup can return one submitter's `tracking_reference` to anyone who reproduces `contact_value`+`host_hint`.** Correctly tenant-scoped and content-hashed (not a raw client key) per the design decision — but low-entropy inputs mean a targeted guesser could retrieve someone else's reference. Low severity today (no lookup endpoint exists yet to make the reference useful) — **must be a hard prerequisite check for whatever story adds a lookup-by-reference endpoint.** Also: two legitimately distinct visits with identical contact+host collapse into one (functional side effect, not a security defect); dedup check runs before the privacy-notice acknowledgment gate.
2. **Retention/purge for `visits`/`outbox_messages` PII confirmed still just a placeholder** (no `DELETE` grant, no purge job, no registration anywhere in the diff) — genuinely not silently assumed done. Same GA-gate status as US-10's `users` table; needs a human compliance owner. Orphaned NULL-host visits must be explicitly covered by that future purge.
3. **Consent capture is a bare acknowledgment flag + version string, not the full versioned/linked-to-document consent framework** `security-privacy.md` describes. Satisfies the placeholder decision but is a genuine DPDP gap requiring Compliance-owner sign-off — not approvable by an agent alone.

## NOTES
- No automated-denial/biometric path exists — confirmed by reading the code, not assumed.
- Command safety (idempotent async outbox write, deterministic globally-unique key, `not_valid_after` expiry) verified sound.
- Envelope encryption independently verified: AES-256-GCM, fresh per-message DEK, ciphertext in `BYTEA`, never cleartext JSONB.
- Never-log rule independently re-verified (source-scanner test re-run, including its injected-violation sanity check — not vacuously green).
- Check-in code handled as a credential throughout: `secrets.token_urlsafe(24)`, only SHA-256 hash persisted, never returned by any endpoint.
- Anti-enumeration verified: uniform portal response regardless of host resolution; uniform 404 for unknown/suspended tenant slug; uniform 403 for nonexistent vs. cross-tenant visit id.
- CAPTCHA-before-tenant-resolution ordering confirmed correct (no timing oracle).
- RBAC confirmed by reading the actual queries: `host` without `view_visits` genuinely sees only their own visits; `reception_security`/`tenant_admin` see the full tenant list.
- RLS/migration hygiene sound: both tables `ENABLE`+`FORCE`, `USING`+`WITH CHECK`, fail-closed, tested `downgrade()`, no `DELETE` grant.
- `visit.requested`'s audit omits `policy_version` (defensible — no RBAC policy governs an anonymous submission) — flagged for an explicit product/compliance decision, not a blocking gap.
- All loop-state-flagged placeholders/process items (7-day check-in validity, 44-file count, non-TDD task 9) are real and honestly disclosed, none silently accepted; none affect a safety property.

**Disposition:** One Blocking item (B1 — the still-open US-10 merge/ship gate, unchanged, correctly preserved). Three Should-fix items, two requiring a human compliance owner (retention registration, consent framework). US-11's own implementation is otherwise sound and matches the approved plan/ADRs.

---

# /verify-story — Track 2: Broader Test Suite (qa-automation-engineer)

Independent re-run: **185 passed, 1 failed (pre-existing US-10 gap, unrelated), 1 skipped** — 183 confirmed matching the loop-state exactly before QA's own 2 added tests.

### Criterion → Test → Result → Evidence (summary; full detail in the agent's report)
1. **State-machine transitions** — PASS. Both directions genuinely tested; Gherkin Scenario 5's reconciliation (concrete `approve`-on-non-`Requested` → 409 call, not a literal `CheckedIn` route) implemented exactly as specified.
2. **Tenant-isolation attempts** — PASS. New public-surface dedup scoping confirmed tenant-scoped; `test_visits_forged_token_cross_tenant.py` (8 tests, two forgery classes × all 3 routes) is a thorough, dedicated proof, not inherited from US-10.
3. **Command idempotency — REAL GAP FOUND, not fixed by QA.** The outbox `idempotency_key` mechanism (ADR-002 §2) is sound. The **public portal's `Idempotency-Key` dedup has a real cross-actor information-disclosure bug**: `_submission_dedup_key` matches on submission content (`contact_value`+`host_hint`) alone — the client's actual header *value* is never checked, only its presence. A new test, `test_portal_dedup_cross_actor_leak.py::test_attacker_with_a_different_idempotency_key_value_can_still_fish_out_victims_tracking_reference`, **passes and proves the exploit**: an attacker who guesses a victim's `contact_value`+`host_hint` and supplies their own arbitrary `Idempotency-Key` retrieves the victim's real `tracking_reference` — directly through the same submission endpoint's own response, with no separate lookup endpoint needed. This is more immediately exploitable than the design-gate review's original characterization (which assumed a future lookup endpoint would be required to make the reference useful) — the disclosure happens right now, at submission time, via the endpoint this story ships. **Recommend escalating this from Should-fix to Blocking** given it's a proven, live information-disclosure defect, not a theoretical future risk. Fix direction (not applied): bind the dedup match to the actual client-supplied key value (e.g. include it in the hash), not just content.
4. **Outage/replay reconciliation** — PASS as a contract test (relay worker itself correctly out of scope); `not_valid_after`-matches-`code_expires_at` test exercises the real encryption path with real data, not hollow.
5. **Audit-event presence** — PASS, all three event types (`visit.requested`/`registered`/`denied`) verified against actual row content, including confirming `visit.denied`'s reason is genuinely coded (not a fragment of the free text).
6. **E2E device simulators** — N/A, no kiosk/device surface.
7. **Load/performance** — no PRD threshold applies; informational measurements taken (portal submission p50 34ms/p95 58ms; approval p50 43ms/p95 49ms). **Gap found and closed**: no prior test exercised the real configured rate-limit thresholds end-to-end; new test confirms exactly the configured capacity (10) succeeds before 429, stable across repeated runs. Configured values (`capacity=10`, `refill=5/min` per-IP; `capacity=60`, `refill=60/min` per-tenant) match the plan's suggested numbers.
8. **Accessibility/Localization** — N/A, backend-only story.
9. **72-hour erasure SLA** — NOT TESTABLE, placeholders only, no purge job built yet (same as US-10).
10. **Avatar-jailbreak/resilience** — N/A.

### Additional scrutiny (as directed)
- The `submission_dedup_key` mechanism's tenant-scoping itself is correctly enforced — the gap is specifically that content alone (not the actual key value) determines the match, inverting the intended protection.
- Task 9's non-TDD construction: coverage is comprehensive everywhere except exactly the adversarial-perspective gap above — consistent with what non-TDD construction tends to miss (validates stated behavior, not attacker behavior).
- `CHECKIN_CODE_VALIDITY` placeholder: clearly named and commented; minor note that it's hardcoded rather than in `settings`, not a DoD defect.

**Overall verdict:** Suite substantially passes and independently confirms the loop-state's report. One real, proven security gap found (dedup cross-actor leak) and reported, not fixed. One coverage gap found and closed (rate-limit e2e). No other blocking gaps.

---

## Combined /verify-story disposition

**Blocking (must remediate before merge):**
1. **B1** — US-10's auth-bypass finding, inherited via `get_current_principal`. Hard merge/ship gate for both branches. Not a US-11 code defect; not fixable inside US-11.
2. **Dedup cross-actor tracking-reference leak** (elevated from the design-gate review's original Should-fix #1, per QA's demonstration that it's immediately exploitable through the story's own endpoint, not a deferred future risk). Fixable inside US-11's own code: bind the dedup match to the actual client-supplied `Idempotency-Key` value, not content alone.

**Should-fix (non-blocking, track but don't need to hold the merge):**
- Retention/purge registration for `visits`/`outbox_messages` PII — needs a human compliance owner.
- Consent/privacy-notice framework (versioned, linked to a specific document, re-consent on version bump) — needs a human compliance owner.
- `visit.requested` audit omits `policy_version` — defensible (no policy governs an anonymous submission), flag for an explicit product decision.
- `CHECKIN_CODE_VALIDITY` hardcoded rather than configurable — minor, not a DoD defect.

**Result: 2 Blocking findings → returns to `/execute-story` for remediation (cycle 1 of max 2).**

---

## Remediation cycle 1 — dedup cross-actor leak (Blocking item 2) fixed

**Branch:** `feature/US-11`. **Scope:** this remediation addresses only Blocking item 2 (the public portal `Idempotency-Key` dedup cross-actor tracking-reference leak). Blocking item 1 (B1, the inherited US-10 auth-bypass merge/ship gate) is explicitly **not** addressed here — it is out of scope for this fix and remains open pending US-10's own remediation; this branch still may not merge to a release branch or deploy until US-10 B1 is resolved.

**Fix applied:** `app/api/portal.py::_submission_dedup_key` now derives the dedup key as `sha256(idempotency_key + "\x1f" + contact_value + "\x1f" + host_hint)` — bound to the client's ACTUAL `Idempotency-Key` header value in addition to submission content, rather than content alone. The call site only computes/checks the dedup key when a header is actually present (`if idempotency_key:` → `dedup_key = ... if idempotency_key else None`), preserving the existing "no header, never dedups" behavior. Tenant scoping (post-`SET LOCAL`, `Visit.tenant_id == tenant.id`) is unchanged.

**Files changed:**
- `services/core-api/app/api/portal.py` — `_submission_dedup_key` signature and hash material; call site; docstring.
- `services/core-api/app/models/visit.py` — `submission_dedup_key` column docstring updated to describe the two-factor binding (column type/constraint unchanged, no migration).
- `services/core-api/tests/test_portal_dedup_cross_actor_leak.py` → renamed to `services/core-api/tests/test_portal_dedup_bound_to_client_key.py`; the exploit-proving assertion is inverted to a fix-proving assertion (attacker's differing key now produces a distinct `tracking_reference`, confirmed via a distinct-row count too); a same-key/same-content sanity test added; the exploit narrative preserved in the module docstring.
- `services/core-api/tests/test_portal_submission.py` — docstring-only clarification on `test_idempotency_key_dedup_is_content_hashed_not_raw_client_key` to reflect the two-factor binding; no assertion changes; all four existing dedup tests (same-key-same-content dedups, same-key-different-content doesn't, per-tenant scoping, no-header-never-dedups) pass unmodified in behavior.

**Migration:** none required. `submission_dedup_key` remains `String(64)` with the existing `uq_visits_tenant_dedup_key` unique constraint on `(tenant_id, submission_dedup_key)` — only the Python-side hash input changed, not the column type, nullability, or constraint shape.

**Verification:** the renamed exploit test, inverted, now demonstrates the attacker's forged-key resubmission creates a separate visit with a distinct `tracking_reference` (previously it demonstrated the leak and passed). Full test suite re-run confirms no regression (see commit for exact pass count). Independent re-verification (a fresh `/verify-story` pass, not self-assessment by the implementing agent) is still required before this finding can be considered closed, per this project's verifier-first policy — this section records that the fix was applied and locally verified, not that it has been independently re-reviewed.
