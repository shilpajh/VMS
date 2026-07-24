# US-07 (DPDP retention purge + right-to-erasure) — Design-Gate Review

Two independent pre-Gate-1 cold reads of `docs/plans/US-07.md` (initial draft). Six Blocking findings between them, none a coding slip — all design decisions to resolve in ADR-005 and the plan before Gate 1, several needing the human compliance owner. Persisted verbatim; the revised plan's "Design-gate disposition" section records how each was resolved.

---

## domain-architect

### Blocking
- **DA-B1 — No reference timestamp to compute the retention clock.** `users` has no `disabled_at` (only created/updated/status), so "180d post-disable" is uncomputable; `visits` has `decided_at` (Denied) and `checked_in_at` but no `checked_out_at`/terminal timestamp, so "90d post-terminal" works only for Denied. `created_at` changes the semantics (post-creation ≠ post-terminal); `updated_at` moves on the scrub itself. Must specify the per-store reference timestamp — almost certainly add `users.disabled_at` + a visits terminal timestamp — in the plan/ADR, not mid-build.
- **DA-B2 — Erasure has no carve-out for an active on-site visit.** Erasing a `CheckedIn` visitor's name mid-visit undermines evacuation mustering / `Safe` accounting. DPDP recognizes life-safety exceptions; a compliance-owner call. Exclude non-terminal visits from erasure or define an explicit safety carve-out, surfaced at Gate 1.
- **DA-B3 — Erasure incomplete for OTP-dispatch outbox rows.** Per ADR-004 §4, `portal.otp.dispatch` rows use `aggregate_type='portal_contact_verification'`, `aggregate_id=verification_id` — anchored to the pcv row, not a visit. A subject who abandoned the OTP flow keeps an encrypted-contact outbox row that erasure-by-visit-id misses. Cascade must delete outbox by BOTH visit_ids AND verification_ids.

### Should-fix
- DA-S1 — Idempotency unachievable for scrub stores: a scrubbed row still matches "terminal+expired" on re-run (re-scrubs, re-counts). Add a `purged_at` marker column; `WHERE purged_at IS NULL`. Also disambiguates the reference timestamp from the scrub's own `updated_at` bump.
- DA-S2 — Staff right-to-erasure unsupported (`erase_subject` takes only a visitor `contact_value`). Add a staff path or fence it explicitly.
- DA-S3 — `audit_events.details` is an append-only, purge-exempt PII sink; make "no PII in `details`, ever" an explicit tested contract in ADR-005, not just an assertion for the two new events.
- DA-S4 — Audit shape under-specified vs NOT-NULL columns (`target_type`/`target_id`/`reason`/`correlation_id`). Specify what fills them (e.g. `target_type='tenant'`/`target_id=tenant_id`, fresh `correlation_id`, masked subject in `details`).
- DA-S5 — Assign the owning module (**Compliance**) and pre-declare the retention domain as an intentional cross-store writer in ADR-005 (as ADR-001 did for the audit sink), so `/graph-query` doesn't misread the edges.

### Notes
FK rationale imprecise for `visits` (no inbound FK; scrub justified by audit-linkage/stat value, not FK); outbox purge should eventually cover all statuses by age; config read needs a tenant predicate too; `data_category` enum names differ from table names (document the mapping); no index on `visits.contact_value` (erasure scans — acceptable for a rare op); `write_audit_event` amendment confirmed genuinely additive; ~16 files, one story is fine.

---

## security-privacy-reviewer

### Blocking
- **SP-B1 — The erasure audit's "masked subject reference" is reversible and lands in the forever store.** A bare `sha256(contact_value)` of a low-entropy email/phone is trivially brute-forceable, and `audit_events` is append-only + purge-exempt — so it persists a recoverable identifier of an erased subject permanently, defeating the erasure. Use a keyed HMAC (Key-Vault key, the existing `app/crypto/hmac_hash.py` pattern) or a genuinely non-identifying reference (counts/affected-row-ids only). Confirm the scheme with the compliance owner; DoD must assert the erasure audit row contains no recoverable contact.
- **SP-B2 — Tenant isolation under BYPASSRLS has no structural backstop.** Running as `vms_migrator` (BYPASSRLS) with "an explicit tenant predicate on every query" as the sole defense is insufficient for irreversible cross-tenant DELETEs — a behavioral test can't prove the invariant, and this is the exact missing-predicate class US-13a SF-2 already hit (caught only because FORCE RLS existed as a backstop, which BYPASSRLS removes). Preferred fix: BYPASSRLS only for the tenant-enumeration read; do the destructive work as the RLS-subject role with a per-tenant `SET LOCAL app.current_tenant_id` loop, so RLS+FORCE structurally prevents cross-tenant writes even if a predicate is forgotten. A human decision at Gate 1.
- **SP-B3 — Incomplete purge coverage leaves three concrete PII classes unpurged forever:** (a) non-terminal/abandoned visits (incl. the orphaned NULL-host visits US-11's review explicitly flagged as must-cover) retain name/contact/purpose/host_hint indefinitely — needs a max-age (by `created_at`) rule; (b) `visits.purpose` (visitor free text, PII-capable) is missing from the scrub list — derive the scrub set from a verified full-column PII inventory, not a hand list; (c) the outbox predicate excludes `dispatched` (the common case whose encrypted payload holds PII+credential) — an inverted predicate; purge `dispatched`-by-age too. "Fresh rows untouched" ≠ "all expired PII reached"; only the latter closes the gap the Problem statement claims to close.

### Should-fix
- Erasure cascade omits `users` and can't serve a cross-channel (email+SMS) subject — DPDP erasure is per-person, not per-contact-string. Extend or explicitly fence (compliance call, tracked).
- Audit-of-purge: `audit_events.tenant_id` is NOT NULL and the table is tenant-scoped → **one `retention.purge` event per tenant** with that tenant's counts, not one for an all-tenants run.
- `--execute` needs a defense-in-depth environment/confirmation guard (typed tenant-slug echo / non-prod assertion), so a fat-fingered `--execute` against the wrong DSN can't proceed. Strengthens, not replaces, the human-gated model. (The "CI deletes real data" path is adequately closed — synthetic `vms_test` only, no scheduler, config guard off.)
- Anonymization ≠ erasure: for the compliance sign-off, confirm the scrubbed `visits` skeleton + retained `tracking_reference`/`correlation_id` + the append-only audit trail + the erasure `subject_ref` together are not a re-identification path.

### Notes
The DPDP-GA-gate posture is handled correctly (placeholders, sign-off kept open — good). Store *table* enumeration is complete and NOT-APPLICABLE dispositions (biometric none, Redis rate-buckets-only) are accurate; the gap is *column/row* coverage (SP-B3). Graph unavailable — the DoD's grep "only the retention domain writes these" must actually be run. Idempotency needs a crash-mid-run test, not just clean-second-run. `retention_policies` schema correct; note the ops config read is the one legitimate BYPASSRLS read (contrast the destructive writes).

---

## Combined disposition
**6 Blocking, 9 Should-fix.** None is a code fix — all are ADR-005/plan design decisions to settle before Gate 1, and several (SP-B1 masking, SP-B2 safety model, DA-B2 erasure carve-out, anonymization-vs-erasure) touch privacy/compliance choices needing the human compliance owner the story already defers to. The DPDP sign-off GA gate stays open and correct. The plan returns to the author for a comprehensive revision + ADR-005, then re-submits to Gate 1.

---

# US-07 — verify-story pass (post-implementation, independent cold reads)

Two independent reviewers read the built `feature/US-07` branch cold (security-privacy-reviewer, qa-automation-engineer). This section is appended below the design-gate findings above; it does not replace them. Every prior design-gate Blocker (DA-B1..B3, SP-B1..B3) was confirmed **resolved in code**, not merely claimed.

## security-privacy-reviewer — verify pass

### Blocking
**None.** All six design-gate blockers verified resolved in code (traced across migrations 0001/0002/0004/0005):
- **SP-B2 (structural isolation):** `vms_purge` is `NOBYPASSRLS` (`app/db/roles.sql`); RLS ENABLE+FORCE + `tenant_isolation` policy confirmed on all four mutated tables; the per-tenant GUC is set before any mutation in both scripts; a forgotten GUC fails closed (single-arg `current_setting` raises). No mutation path reaches a target table without the GUC.
- **DA-B1:** `users.disabled_at` set on disable / cleared on re-enable (`app/api/identity.py`); clocks are `disabled_at`/`decided_at`/`created_at`, never `updated_at`.
- **SP-B3:** all six visit PII columns scrubbed incl. `purpose`; outbox deleted by age across all statuses (no status filter).
- **DA-B3:** erasure deletes outbox by `visit_ids + verification_ids` (both anchors).
- **DA-B2:** `OnSiteErasureRefused` for `CheckedIn`/`Safe`; same states excluded from purge.
- **SP-B1:** erasure `subject_ref` is a keyed HMAC; `audit_events` is INSERT-only for `vms_purge`.

### Should-fix — all remediated this pass
- L: 🟡 stray `node_modules/.vite/vitest/…/results.json` committed on branch (US-13a class). **Fixed** — untracked + root `node_modules/`/`.vite/` gitignored (`f8c408b`).
- L: 🟡 purge audit `details` had counts+cutoffs but not the resolved window/`policy_version`; not self-describing. **Fixed** — `retention_seconds` per category + `policy_version` now recorded (`eb68630`).
- L: 🟡 `_ABANDONED_STATUSES` covers only `Requested`/`Registered`; `Held`/`Awaiting*`/`Checked-out` also hold PII (unreachable today). **Fixed** — ADR-005 forward-requirement note added (`eb68630`).

### Notes
- `set_purge_tenant` f-string-interpolates a DB-sourced UUID (never user input) — safe, same established pattern as `set_tenant_context`; `set_config(..., true)` would remove interpolation as defense-in-depth.
- `vms_purge` has `SELECT` on `audit_events` (for `INSERT…RETURNING`), slightly broader than plan's "INSERT only" — RLS-scoped, acceptable.
- `erase_visitor` writes an audit row even on 0 matches (unlike `erase_staff`) — harmless, PII-free; left as-is.

## qa-automation-engineer — verify pass

**Suite:** 341 passed (334 pre-existing + 7 new coverage-gap tests). Every DoD bullet mapped to a passing test.

### Real bug found — FIXED
- **`erase_subject.py` CLI echoed the raw `--value` contact to stdout** (dry-run + APPLIED), violating the DoD "no PII in logs" bullet — a real leak path when ops-script stdout is captured to a shared log. Proven by `test_erase_subject_cli_output_contains_no_raw_contact_pii` (initially FAIL). **Fixed** in `e212f52` (masked, non-PII label); the test now passes.

### Coverage gaps closed (new tests, `tests/test_retention_coverage_gaps.py`) — all PASS
- All six visit PII columns scrubbed, both purge and erasure paths (prior tests spot-checked 2–3).
- Fresh rows byte-identical (full row tuple) after `--execute`, all four stores.
- Crash-mid-run-then-rerun idempotency: resumed run counts only remaining rows, no double-count in the audit, third run touches 0.
- ≤72h erasure SLA: `erase_visitor` completes synchronously in one transaction (measured 0.0536s), no deferral outbox row created.
- `disabled_at` stamped/cleared via the real `PATCH …/users/{id}` API (prior test only checked a fresh user's NULL).

### NOT TESTABLE (explicit)
Real scheduler/cron wiring; real Key Vault HMAC provider; real production-environment activation; the compliance-owner sign-off items (final windows, anonymization-vs-erasure per DPDP category, on-site life-safety carve-out semantics, re-identification of the scrubbed skeleton) — all named open in the plan/ADR-005, none adjudicable by a test.

---

## verify-story disposition
**Zero Blocking. One real bug (CLI PII leak) + three Should-fix — all remediated in remediation cycle 1** (`f8c408b`, `e212f52`, `eb68630`), full suite green at 341. Every mapped acceptance criterion passes or is explicitly dispositioned NOT TESTABLE. **Exit criteria met → `/document-story`.** The DPDP-GA compliance sign-off gate remains open by design (Constraint 1) and is out of scope for this story's merge.
