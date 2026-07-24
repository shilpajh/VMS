# US-01 (Pre-registered check-in, hardware-free QR slice) — Verify-Story Review

Design-gate cold reads (domain-architect, security-privacy-reviewer) ran before Human Gate 1 and are recorded in full in `docs/plans/US-01.md`'s "Design-gate review disposition" section — not duplicated here. That pass found one shared Blocking defect (an earlier draft's unencrypted credential-grant outbox payload, unbuildable against `outbox_messages.payload_key_ref`'s `NOT NULL` constraint and divergent from ADR-002) which was corrected in the plan before execution began. This document covers the post-implementation `/verify-story` pass only.

---

# /verify-story — Track 1: Compliance/Security (security-privacy-reviewer, read-only)

Reviewed `git diff main..feature/US-01` cold against the approved plan. Scope confirmed: diff matches the plan (nothing crept in beyond it; nothing from the plan was silently dropped). All 233 backend tests independently re-run by the reviewer; all pass.

## BLOCKING

**None.** The design-gate's Blocking finding (unencrypted credential-grant payload) was independently re-verified as **actually fixed in code** — `checkin_visit()` in `app/domain/visits/service.py` runs both the credential-grant and arrival-notify payloads through `encrypt_payload(...)` before writing either `OutboxMessage` row; no plaintext special case, no discriminator column.

Independently verified clean, against the actual code (not the plan's prose):
- **Tenant isolation** — the guarded `UPDATE` filters `Visit.tenant_id == tenant_id`; the reload and `User.email` lookup are both tenant-scoped; `tenant_id` derives from `principal.tenant_id`, itself only trusted after full signature+issuer+audience validation against the DB-stored `entra_tenant_id` (US-10's B1 fix). No new tables — RLS posture unchanged.
- **State machine** — `("Registered","checkin_verified"): "CheckedIn"` is the only new row in the frozen `_TRANSITIONS` table; no generic "apply any trigger" bypass exists.
- **No automated denial** — `watchlist_clear()` fails open (never denies); the audit event asserts nothing about a watchlist check having run; `Registered -> Held` (`watchlist_match`) is genuinely absent from `_TRANSITIONS`, not half-wired.
- **Audit completeness** — `visit.checked_in` carries `actor`, `correlation_id`, `reason="qr"`, `policy_version`, server-generated timestamp. All present.
- **Idempotency/expiry** — both outbox rows use deterministic `sha256(...)` idempotency keys; both encrypted.
- **Timing oracle** — `checkin_code_expires_at > now` sits in the same `WHERE` as hash/tenant/status; no separate post-flip expiry check; `NULL` fails closed by SQL semantics.
- **Secrets/logging** — no logger/print calls touch the plaintext code, host email, or visitor name in new backend code; `VisitOut` never serializes `checkin_code_hash` or the plaintext code.
- **AuthN/AuthZ** — `checkin_confirm` permission required before any DB touch; one uniform 404 across every rejection cause.
- **Retention/erasure** — `visit-arrival-notify.yaml` documents registration under the same standing PII-purge GA gate as `visit.checkin_code.dispatch`.

## SHOULD FIX — both remediated

1. **Guard return values discarded; `watchlist_clear()`'s result feeds no conditional.** Correct and safe for this story (no real watchlist exists), but flagged as a latent trap: a future watchlist story must not just flip the stub's return value and branch on it here — a real match must route through the separate `Registered -> Held` transition for human review, never fail this transition directly. **Fixed**: added an explicit comment at the call site in `service.py` stating this and directing the future rewiring to the correct transition.
2. **Plan file had two stale lines contradicting the shipped (correct) code**: the file map said the outbox writes were "one unencrypted, one envelope-encrypted" (code encrypts both) and still listed a `PERMISSION_POLICY_VERSION = "v3"` bump (the Scope amendment already established none was needed, and the code correctly didn't add one). **Fixed**: both lines corrected in `docs/plans/US-01.md`.

## NOTES

- Post-UPDATE visit reload originally selected by `(tenant_id, checkin_code_hash)` only — safe given 256-bit random codes, but adding a `status == "CheckedIn"` filter is marginally more defensive. **Applied** as a belt-and-suspenders change (not a new guarantee — the guarded UPDATE already provides the real safety property).
- `reason="qr"` as a stand-in for the contract's `verification_method` audit field is audit-schema debt already recorded in ADR-003 — reconfirm at `/release-readiness`.
- Watchlist stub **and** the unwired `Registered -> Held` edge are both genuine, correctly-flagged release-blockers for any release claiming automated watchlist coverage — reconfirmed present, neither is a shipped control.
- Credential-grant `expiry` reuses `checkin_code_expires_at` (arrival deadline, not credential-validity window) — known-wrong placeholder, documented as an ADR-003 open question.
- `getAccessToken.ts` extraction (shared MSAL token flow) is a reasonable DRY refactor within scope, not scope creep.

---

# /verify-story — Track 2: Broader Test Suite (qa-automation-engineer)

Re-ran both suites independently: 233 backend (232 pre-existing + 1 new perf test), 16 frontend (pre-remediation) — all passing.

### Criterion → Test → Result → Evidence

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | E2E device simulator (QR scanner) | **NOT APPLICABLE** | `VisitCheckinRequest.checkin_code` is a plain `str`; QR *decoding* happens entirely client-side, out of this story's backend scope. No decode/parse step exists server-side for a device simulator to stand in for. |
| 2 | Load/perf vs PRD thresholds | **PASS locally** (with caveat) | New `test_visit_checkin_performance.py`: 30 real HTTP round trips, p50=42–43ms, p95=61–72ms, max=73ms vs. the PRD's 1000ms threshold. Explicit caveat: single-process, in-process ASGI, local Postgres, no concurrency — a floor-latency sanity check, not a substitute for real load testing (500 concurrent check-ins/site cluster requires a real load-test environment that doesn't exist yet). |
| 2b | "Host notified < 10s" | **NOT TESTABLE** | No relay/notification worker exists to consume `visit.arrival.notify` — only the cloud-side intent is recorded. Outbox-write latency (~same 42–72ms) answers a different, easier question than "how fast is the host notified" — reported as not testable rather than substituted. |
| 3 | Accessibility (WCAG 2.1 AA) | **2 gaps found, both fixed** | Gap 1: no focus management after submission (form unmounts, focus reverts to `<body>`) — WCAG 2.4.3. Gap 2: error message not linked to the input via `aria-describedby`/`aria-invalid` — WCAG 3.3.1. Both remediated in `CheckinPage.tsx` (focus moved to the success region on success; `aria-invalid`/`aria-describedby` added on error), with new tests (`CheckinPage.test.tsx`: focus-after-success, aria-linkage, keyboard-only submission). |
| 4 | Localization completeness | **PASS** for this story; app-wide pre-existing gap flagged | Every user-facing string in `CheckinPage.tsx` goes through `t()` with a key + English default — zero hardcoded strings. Flagged (not a regression): `apps/web/src/i18n.ts` has empty resource bundles for every locale app-wide (pre-existing, true before US-01, affects every page equally) — "completeness" can only mean "correctly routed through the i18n API" until real translations exist anywhere in the app. |
| 5 | 72-hour erasure SLA | **NOT TESTABLE** | No purge/erasure job exists anywhere in `services/core-api` (confirmed by repo-wide grep) — matches the story's own scope (US-07 owns the purge mechanism, not yet built). |
| 6 | Avatar-jailbreak resistance | **NOT APPLICABLE** | No avatar code exists in the repo at all (any story); this story's diff doesn't touch any avatar path. |
| 7 | Resilience (network-loss/reconnect) | **NOT APPLICABLE** for edge/kiosk chaos testing | `apps/edge-connector` remains a README scaffold — no offline-queue/reconnect-replay path exists to test. The one resilience-relevant property this story owns (atomicity: a failed guard leaves zero side effects) is already covered by the pre-existing `test_checkin_with_expired_code_raises_invalid_checkin_code_error_and_no_side_effects` and `test_concurrent_double_checkin_only_one_succeeds`. |

---

## Combined disposition

**Zero Blocking findings** from either track. All Should-fix items (2 from Track 1, 2 accessibility gaps from Track 2) were remediated in follow-up commits on `feature/US-01`, re-verified green: **233 backend tests, 19 frontend tests, `tsc -b` clean, `oxlint` clean.**

All 4 Gherkin scenarios pass. Every PRD acceptance-criterion component for the QR path is either passing (< 1s retrieval, measured locally), explicitly NOT TESTABLE (host-notify delivery timing, 72-hour erasure), or explicitly NOT APPLICABLE (device simulator, avatar, edge/kiosk resilience) with reasoning recorded — none silently skipped.

**Standing release-blockers, reconfirmed (not resolved by this story, by design)**:
- `watchlist_clear()` stub and the unwired `Registered -> Held` edge — no automated watchlist coverage exists; must resurface at `/release-readiness`.
- Credential-grant `expiry` placeholder (reuses arrival-deadline, not a real credential-validity window) — ADR-003 open question.
- Retention/purge registration for `visit.arrival.notify` — depends on US-07's not-yet-built purge mechanism; documented in the contract, not implemented.
- App-wide i18n resource bundles are empty (pre-existing, all stories) — no real non-English translation exists anywhere to verify against yet.

**Exit**: zero blocking findings, every mapped acceptance criterion passes or is explicitly dispositioned → proceed to `/document-story`.
