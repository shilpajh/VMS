# US-13b (Portal redesign: fix form + card layout + tracking lookup) — Verify-Story Review

Frontend redesign consuming the merged US-13a backend, plus the re-applied US-01 CORS fix. Two independent passes.

---

## Track 1 — Compliance/Security (security-privacy-reviewer, read-only)

**Verdict: no Blocking findings; approved from a security/privacy standpoint.** Scope matches the approved plan (frontend portal + the one CORS enabling fix + traceability docs). The standing backend checklist (tenant isolation, state machine, automated denial, biometric, audit, command safety, retention, authZ) is explicitly N/A — this is a UI over US-13a's already-reviewed endpoints with no data surface of its own.

High-value checks, all PASS:
- **Anti-enumeration in the UI** — `portalApi.ts` throws one `PortalApiError` for every non-OK response (and network failures reject identically); `PortalRequestForm`/`TrackingLookup` render one generic message each, never branching copy on HTTP status. `PortalTrackingStatus` is typed to exactly `status`/`visitor_full_name`/`host_hint`, so a hypothetical leaked `host_display_name`/`checkin_code` is structurally unrenderable (proven by the tracking test that includes extra fields).
- **No client-side status/authz policy** — the only client gate is the group→size validity mirror (a "don't round-trip a guaranteed 422" convenience), not an authorization decision.
- **No secrets/PII in the frontend** — no localStorage/sessionStorage/cookie/console; only Turnstile's public test sitekey.
- **Consent** — privacy-notice acknowledgment still required; body still sends `privacy_notice_acknowledged`/`version`.
- **CORS** — explicit allowlist (never `*`), `allow_credentials=True` paired with explicit origins; `test_cors_middleware.py` asserts the header echo (not vacuous).
- **Contract fidelity** — `portalApi.ts::PortalSubmission` matches US-13a's `PortalVisitRequestCreate` field-by-field; `expected_group_size` sent only for groups (satisfies the backend's group→size validator).

Notes (both remediated): `PortalApiError.httpStatus` is a latent affordance — commented that it's log-only and UI copy must never branch on it; the group-size client guard checked only empty — tightened to reject `< 1` to fully mirror the backend's `ge=1`.

---

## Track 2 — Broader Test Suite (qa-automation-engineer)

Ran both suites (29 frontend, 297 backend green).

| # | Criterion | Result |
|---|---|---|
| 1 | Accessibility (WCAG 2.1 AA) | Mostly compliant; **1 real defect found & fixed** (below). Single `<main>` (PASS), labels/fieldsets (PASS), role=status/alert (PASS), group-size aria-invalid/describedby (PASS), keyboard-completable (PASS). |
| 2 | Localization | PASS — every string via `t()` except one hardcoded placeholder (`REQ-000000000000`), now routed through `t()`. Pre-existing app-wide empty-resource-bundle gap noted (not a regression). |
| 3 | Responsive / no h-scroll | **NOT TESTABLE automatically** (jsdom can't measure layout). Static Tailwind review: single-column below breakpoints, `w-full h-auto` illustration in a `max-w` box, no fixed widths → no apparent regression. A real narrow-viewport Playwright check would convert this to a measured pass. |
| 4 | Contract-drift regression coverage | **Partial — real gap.** Frontend tests assert the submitted body shape (catches the *component* dropping a field) but mock fetch, so they wouldn't catch the actual failure mode (backend DTO changing while the hand-maintained `PortalSubmission` interface drifts). Recommended follow-up: a contract test validating `PortalSubmission` against `packages/contracts/openapi/visits.yaml`. Not fixed here — flagged. |
| 5 | CORS enabling fix | PASS — 3 non-vacuous assertions + a live over-the-wire curl check confirming the header. 297 backend green. |
| 6 | E2E / device / avatar / edge | NOT APPLICABLE — no device/kiosk/avatar/edge surface. |
| 7 | 72h erasure / retention | NOT APPLICABLE / inherited — no new PII store (US-13a owns `portal_contact_verifications`). |

### The a11y defect (fixed) — missing focus-to-result on submit
`PortalRequestForm`'s success div replaced the form (submit button unmounts) with no `ref`/`tabIndex`/`.focus()`, so focus reverted to `<body>` for sighted keyboard users — WCAG 2.4.3, the same bug class US-01's CheckinPage already fixed and this DoD promised to match. **Fixed** by adding the `useRef`/`tabIndex={-1}`/`useEffect(...).focus()` triplet. The reviewer's failing `PortalRequestForm.focus.test.tsx` is now green and committed.

### Governance escalation (resolved by documentation, not revert)
The reviewer correctly flagged that the two-panel/SVG restyle contradicts the plan's Gate-1 Decision 2 (plain grid; SVG rejected) — a spec-contradiction that should stop-and-return-to-Plan rather than ship silently. **Context the reviewer lacked:** the human explicitly directed this change mid-`/execute-story` (confirmed via a direct question), so it was a human Gate-1 amendment, not an agent workaround. Resolved by recording the amendment in `docs/plans/US-13b.md` (Decision 2 reversed, visual-only, `PortalIllustration.tsx` added to the file map) so plan and code agree — the correct resolution for a human-approved change.

---

## Combined disposition
**Zero Blocking findings.** All Should-fix / Note items remediated: the WCAG focus defect (fixed + tested), the group-size `< 1` guard, the `httpStatus` misuse guard-comment, the hardcoded placeholder i18n, and the governance amendment (documented). Final: **30 frontend tests, 297 backend tests passing; tsc + oxlint clean.**

Every mapped acceptance criterion passes or is explicitly dispositioned. NOT-TESTABLE/NOT-APPLICABLE items (responsive measurement, device/avatar/edge, retention) recorded with reasoning.

**Standing follow-ups (not blocking):**
- Contract-drift test (frontend `PortalSubmission` vs OpenAPI schema) — recommended so a future backend DTO change fails a frontend build instead of production 422s.
- A real narrow-viewport layout check to convert the responsive criterion from static to measured.
- The staff sign-in shell (`App.tsx`) is unstyled and real Entra sign-in can't complete without a real app registration — both explicitly deferred by the human (separate story / skip real login for now), not US-13b defects.

**Exit**: zero blocking findings, all criteria dispositioned → `/document-story`.
