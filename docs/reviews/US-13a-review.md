# US-13a (Portal OTP verification + tracking lookup, backend) — Verify-Story Review

Pre-Gate-1 design-gate cold reads are in `docs/reviews/US-13-review.md` (the original combined US-13). This document is the post-implementation `/verify-story` pass on the backend split (US-13a).

---

## Track 1 — Compliance/Security (security-privacy-reviewer, read-only)

Reviewed `git diff origin/main..feature/US-13a` against the approved plan, line-by-line, plus ran the suite against live Postgres as the RLS-subject `vms_app` role and read the two most security-critical tests to confirm they aren't vacuous.

### BLOCKING
**None.** All 12 security-relevant claims independently verified true in the implementation (not merely asserted), each backed by a genuine passing test: tenant isolation (RLS enable+force + explicit `tenant_id` predicates on every read/write, exercised as `vms_app`); keyed-HMAC OTP/token hashing (never bare SHA-256, plaintext only inside the envelope-encrypted dispatch); constant-work verify (instrumented statement-count test); supersede (per-contact not per-row cap); single-use race-safe contact-scoped token; CAPTCHA-before-DB on both OTP endpoints + dedicated Redis-namespace buckets; tracking lookup returns own-details-only with byte-identical 404; envelope encryption correct (no repeat of US-01's unencrypted-payload bug); consent gated at otp/request; PII-free audit; no logging of OTP/token/contact/key; config flag gates the token requirement.

### Should-fix — both remediated
- **SF-1** — Four out-of-scope files (`Smart_VMS_PRD_v2.2 latest.docx`, `visitor_management_prototype (1).jsx`, two `Zone.Identifier`) were swept onto the branch by `git add -A`, violating the plan's file-map fence. **Fixed**: `git rm --cached` (removed from the tip) + `.gitignore` rules added. They remain in branch history (commit `5bb091a`) — **the PR should be squash-merged** so the stray binary never reaches `main`.
- **SF-2** — The constant-work attempt-increment UPDATE filtered on `id` only (relied on FORCE RLS as its sole tenant guard, unlike every other write). **Fixed**: added an explicit `tenant_id ==` predicate (defense-in-depth).

### Notes
- **N-1** (fixed) — Concurrent `otp/request` for one contact could momentarily leave two live rows → `_current_row`'s `scalar_one_or_none()` would raise `MultipleResultsFound` → 500. Fixed: `ORDER BY created_at DESC LIMIT 1` + `.first()` (newest wins), with a regression test.
- N-2 — An OTP is re-verifiable until its token is consumed (each re-verify overwrites the prior token hash; still requires the correct code). Not a weakness; documented.
- N-3 — Constant-work statement-count test asserts no-OTP vs wrong-code; expired/exhausted follow the same sentinel branch by inspection.
- N-4 — The exhaustion-transition audit is a single-shot extra statement on the exact 5th attempt; leaks nothing an attacker who already made 5 attempts didn't know. Accepted.
- N-5 — Abandoned-row PII purge is documented (ADR-004 O2) but deferred to US-07; until then abandoned rows retain `contact_value`. (Happy-path rows no longer accumulate — see qa #1 remediation below.)
- N-6 — `resolve_public_tenant` string-interpolates a validated UUID into `SET LOCAL` (Postgres `SET` takes no bind params); reused verbatim from US-11, confirmed not an injection vector.

---

## Track 2 — Broader Test Suite (qa-automation-engineer)

Confirmed no `apps/web` changes (UI is US-13b). Re-ran the suite (286 → now 294 with remediation tests).

| # | Criterion | Result |
|---|---|---|
| 1 | E2E device simulators | **NOT APPLICABLE** — OTP delivery is outbox-based; no kiosk/printer/scanner/biometric/panel in this story. |
| 2 | Load/perf vs PRD thresholds | **Baseline measured** (no PRD latency AC for these endpoints, none invented). Local floor-latency: otp/request p50=47.7ms/p95=69.8ms; otp/verify p50=37.9ms/p95=48.2ms; lookup p50=29.8ms/p95=34.8ms. Committed as `test_portal_otp_and_lookup_performance.py`. |
| 3 | 72h erasure / retention | **NOT TESTABLE** (purge job is US-07, correctly documented as ADR-004 O2). **qa #1 real finding (fixed)** — see below. |
| 4 | Avatar-jailbreak | **NOT APPLICABLE** — no avatar code. |
| 5 | Resilience / atomicity | **NOT APPLICABLE** for edge/kiosk; the atomicity property (rejected submission → zero visits, no partial state) was a coverage gap — **now tested** in `test_portal_otp_dispatch_and_atomicity.py`. |
| 6 | Command idempotency (mandatory suite) | Mechanism correct; was untested — **now tested** (dispatch idempotency-key determinism + uniqueness + per-row resend). |
| 7 | Rate-limit thresholds enforced | Real configured thresholds for the 5 new buckets were only exercised via the always-allow double — **now tested end-to-end** against real Redis/config in `test_portal_otp_and_lookup_rate_limit_thresholds.py`. |

### qa #1 — real integrity finding (fixed)
`consume_verification_token` did a guarded `UPDATE ... SET consumed_at`, but the model docstring, migration comment, and ADR-004 §6 all stated a **DELETE** occurs on consume. The code contradicted its own docs, `contact_value` PII accumulated on the happy path (not just abandoned rows), and the migration's `DELETE` grant was dead. **Fixed by making the code actually DELETE** (guarded `DELETE ... RETURNING`): single-use is now enforced by row absence, PII is removed immediately on the happy path, the grant is used, and all three docs are now accurate. Dedup-before-consume in the submission endpoint means a legitimate idempotent retry returns the existing reference and never reaches the consume, so DELETE is safe.

---

## Combined disposition
**Zero Blocking findings.** Two security Should-fix (SF-1, SF-2), one crash-risk Note (N-1), one broader-pass integrity finding (qa #1), and three coverage gaps (qa #5/#6/#7) — **all remediated** on `feature/US-13a`, re-verified: **294 backend tests passing.**

Every mapped acceptance-criterion component either passes, is explicitly NOT TESTABLE (retention purge job → US-07; real load testing → needs a load environment), or NOT APPLICABLE (device simulators, avatar, edge/kiosk resilience) — none silently skipped.

**Standing items carried to Gate 2 / follow-up (not blocking):**
- Squash-merge the PR (SF-1: stray files remain in branch history).
- Abandoned/expired-row PII purge (ADR-004 O2) depends on US-07's not-yet-built purge mechanism.
- Rate-limit thresholds are first-cut values (ADR-004 O1), config-tunable.
- The OTP relay worker (ADR-004 O3) is a hard prerequisite before `portal_otp_required` can be turned on in any real environment.
- The orphaned US-01 CORS fix is still not in `main`; US-13b (the UI) will need it.

**Exit**: zero blocking findings, all criteria dispositioned → proceed to `/document-story`.
