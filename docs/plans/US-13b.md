# US-13b: Portal Redesign — fix the submission contract break + card layout + tracking lookup

Status: Approved (Human Gate 1, 2026-07-24 — refreshed against the merged US-13a backend; supersedes the pre-implementation draft. CORS fix + traceability kept in-scope per approval.)

> Frontend redesign that consumes the US-13a backend (now merged to `main`). **Refreshed after US-13a shipped**, which changed two things the original draft couldn't know: (1) the current portal form is now *broken* against the backend, and (2) the OTP flow can't complete for real users yet. Two Gate-1 decisions were taken (below). Design reference: `visitor_management_prototype (1).jsx`'s `VisitorPortal` + the prototype screenshot.

> **Gate-1 amendment — 2026-07-24 (during execution, human-directed): Decision 2 reversed to MATCH the prototype's look.** After seeing the plain-grid build, the human explicitly asked (mid-`/execute-story`, confirmed via a direct question) for the portal to look like the prototype — the two-panel illustrated layout (blue left panel with acme branding + reception SVG, cards on the right) that Decision 2 below originally rejected. This is a human Gate-1 amendment, not an agent working around the plan: the styling change (`PortalPage.tsx` two-panel layout + new decorative `PortalIllustration.tsx`) was built per that instruction. Scope of the amendment is **visual only** — the prototype's OTP flow (no relay worker) and its Feedback/manual cards (no PRD grounding) remain out of scope, re-confirmed with the human at the same time. The rejected-alternative note and Decision 2 text below are left as originally written to preserve the trail; this amendment supersedes them.

## Part A — Intent

### Problem
US-13a (backend, merged) made `purpose`, `group_type`, and `identity_verification_choice` **required** on `POST /public/portal/{slug}/visit-requests`. The current `PortalRequestForm.tsx` (from US-11) does not send them, so **a real portal submission now returns 422** — the public portal is currently broken on `main`. Separately, PRD 3.1 wants a portal that also lets a visitor "look up live status … using [the tracking] reference, with no account needed"; US-13a shipped that lookup endpoint but nothing renders it. The product reference shows a multi-card landing page (Request a visit / Track a visit / Log in).

### Solution
- **Fix the break**: the Request-a-visit form sends the now-required `purpose`/`group_type`/`expected_group_size`/`identity_verification_choice` (plus the existing name/contact/host/consent/CAPTCHA fields), so real submissions succeed again (the `portal_otp_required` flag is off, so no verification token is needed — submission takes US-13a's US-11-compatible consent path).
- **Redesign** `apps/web/src/portal` into the reference's card layout — Request a visit, Track a visit (drives US-13a's lookup endpoint), Log in (links to the existing MSAL staff shell) — as a plain responsive grid consistent with the app's current minimal style.
- **Enabling fix**: re-apply the CORS middleware (orphaned from US-01) so the browser can actually reach the API — without it, every portal fetch is blocked and this UI can't be browser-tested.
- **Housekeeping**: refresh `specs/traceability.md` (rolled into this branch per the US-13a close-out decision).

### Gate-1 decisions taken (this story couldn't have known these pre-US-13a)
1. **No OTP wizard in this story.** US-13a's OTP endpoints require CAPTCHA, and no SMS/email relay worker exists to deliver an OTP — a real visitor would hit a dead end at the OTP step. Since `portal_otp_required` defaults **off**, submission works *without* a verification token. So US-13b ships a direct Request-a-visit form (no contact→OTP→details wizard); the OTP wizard becomes its own story once the relay worker (ADR-004 O3) exists. This keeps the portal fully usable for real visitors now, consistent with US-13a's config-gate intent.
2. **Plain responsive grid**, not a pixel-copy of the prototype's illustrated two-panel layout — faster, and it doesn't introduce bespoke styling the rest of the app doesn't use. Structure (three cards, the fields) matches; visual richness doesn't.

### Out of scope (explicit scope-creep fence)
- **The OTP wizard** (contact→OTP→details) — deferred (decision 1). The `otp/request`/`otp/verify` endpoints exist and are tested (US-13a) but get no UI here.
- **All backend/API/contract work except the CORS re-apply** — no new endpoints, no changed server behavior. The CORS middleware is a dev-infrastructure enabling fix (already reviewed in US-01, orphaned before that PR), not new product behavior.
- **Feedback widget & manual-download** (in the prototype) — no PRD grounding, no backend; dropped.
- **Real ID/selfie upload** — the form renders `identity_verification_choice` (upload-now vs send-to-host) as US-13a's inert intent enum only; no file picker that stores/transmits anything (US-03 territory).
- **Group-member entry** — renders `group_type` + `expected_group_size` (a count); no per-member repeater.
- **Showing the check-in code in the tracking card** — US-13a's lookup never returns it; the card shows status + the visitor's own submitted details only.

### Risks (non-obvious failure modes)
- **The form must send exactly what US-13a requires or stays 422.** `group_type: "group"` additionally requires `expected_group_size` (US-13a's DTO validator → 422 without it) — the form must enforce that client-side too, or a group submission fails server-side.
- **Anti-enumeration is a backend property the UI must not re-leak.** Every non-OK response (400/404/422/429/network) renders one identical generic message — exactly as US-11's form already does. The tracking card must render only the three fields the server returns (`status`, `visitor_full_name`, `host_hint`) and never assume a resolved-employee-name or check-in-code field exists.
- **CORS re-apply must match US-01's reviewed version** — explicit origin allowlist (never `*`, since staff routes carry `Authorization`), default scoped to the Vite dev origin; not a fresh, looser take.
- **WCAG on the (now single-step) form + tracking card** — labelled inputs, `role="alert"`/`role="status"` live regions, keyboard-completable, focus to the result on submit — the standard US-01's `CheckinPage` met.
- **First multi-column responsive layout** in this app — the card grid must not introduce horizontal-scroll on a narrow viewport.

## Part B — Contracts
No new contract. Consumes US-13a's already-merged OpenAPI (`submitPortalVisitRequest`, `trackPortalVisitRequest`). The CORS change is server config, not an API/contract change. No state-machine, permission, or schema change.

### Gherkin scenarios
```gherkin
Feature: Portal redesign (US-13b)

  Scenario: A visit request submits with the now-required fields
    Given I am on the acme-corp portal landing page
    When I fill in name, contact, host, purpose, group type and identity-verification choice
    And I acknowledge the privacy notice and complete the CAPTCHA and submit
    Then I see the tracking reference the server returned

  Scenario: Choosing "group" requires a group size before submit
    Given I am filling in the request form
    When I select group type "group" and leave the group size empty
    Then the form blocks submission and asks for the group size

  Scenario: The tracking card renders server status without leaking anything extra
    Given I have a tracking reference
    When I enter it in the Track-a-visit card and check status
    Then I see the status and my own submitted details
    And I never see a resolved employee host name or a check-in code

  Scenario: Every failure renders one identical generic message (anti-enumeration preserved)
    Given the server returns 400/404/422/429 or a network error
    Then the UI renders the same generic error, never a status-specific one
```

## Part C — Plan

### Definition of done
- All 4 Gherkin scenarios pass as Testing-Library tests.
- The Request-a-visit form sends `visitor_full_name`, `contact_channel`, `contact_value`, `host_hint`, `purpose`, `group_type`, `expected_group_size` (when group), `identity_verification_choice`, `privacy_notice_acknowledged`, `privacy_notice_version`, `turnstile_token` — matching US-13a's DTO exactly; a real submission returns 202 (verified against the OpenAPI types, not hand-rolled).
- `group_type = "group"` disables/blocks submit until `expected_group_size` is provided — tested.
- Privacy-notice acknowledgment + a completed CAPTCHA are required before submit (unchanged US-11 behavior, preserved) — tested.
- The Track-a-visit card renders `status` + `visitor_full_name` + `host_hint` only; a test asserts it never renders a field that would only exist if the server returned a resolved employee name or a check-in code; a 404/unknown renders the one generic message.
- Every non-OK response across the form and the tracking card renders one identical generic message — tested across 400/404/422/network.
- WCAG 2.1 AA: labelled inputs, `role="status"`/`role="alert"`, focus-to-result on submit, keyboard-completable — tested.
- All user-facing strings via `t()`; no hardcoded copy.
- The Log-in card links into the existing MSAL staff shell (no auth code change).
- CORS middleware re-applied (matching US-01's reviewed version); `curl -H "Origin: http://localhost:5173" .../health` returns the `access-control-allow-origin` header; the backend suite stays green.
- `specs/traceability.md` refreshed (Status column + rows for US-10/US-01/US-13a/US-13b).
- `tsc -b` and `oxlint` clean; no `apps/web/src/portal` horizontal-scroll regression on a narrow viewport.

### File map

**Frontend (apps/web/src/portal)**
- `PortalRequestForm.tsx` — amend: add the now-required fields (purpose input, group_type radio, conditional expected_group_size, identity_verification_choice radio); keep the existing Turnstile + privacy-ack.
- `PortalPage.tsx` — amend: two-panel layout (left branding/illustration panel + Request a visit / Track a visit / Log in cards), replacing the single-form page. (Per the Gate-1 amendment above — originally a plain grid.)
- `PortalIllustration.tsx` — new (Gate-1 amendment): the decorative reception-scene SVG for the left panel, `aria-hidden`.
- `TrackingLookup.tsx` — new: the Track-a-visit card (drives `GET .../visit-requests/{ref}`).
- `portalApi.ts` — new: typed fetch wrappers for submit + lookup (request shapes in one place, matching the contract).
- Tests: `PortalRequestForm.test.tsx` (amend — new fields, group-size rule, generic error), `TrackingLookup.test.tsx` (new), `PortalPage.test.tsx` (new — three cards, login link).

**Backend (enabling fix only — the orphaned US-01 CORS middleware)**
- `services/core-api/app/main.py` — re-add `CORSMiddleware` (US-01's reviewed version).
- `services/core-api/app/config.py` — re-add `cors_allowed_origins` (explicit allowlist, Vite dev default).

**Docs**
- `specs/traceability.md` — refresh (Status column + US-10/US-01/US-13a/US-13b rows).

### User journey (demo path)
1. Anonymous visitor opens `/portal/acme-corp`, sees the three-card layout.
2. In Request a visit: fills name/contact/host/purpose/group-type/identity-choice, ticks privacy, completes the (test-key) CAPTCHA, submits → 202 + tracking reference shown.
3. Pastes the reference into Track a visit → sees status `Requested` + their own name + typed host string (no employee name, no code).
4. A host approves via the existing API/flow → the tracking card, on re-check, shows `Registered`.
5. Log in card → the existing staff MSAL shell (real Entra needed to actually sign in — unchanged).

### Numbered tasks
1. **Re-apply CORS** (`main.py` + `config.py`, US-01's reviewed version). Test: backend suite green; `Origin` header echoed on `/health`.
2. **`portalApi.ts`** typed wrappers (submit + lookup). Test: correct URL/body/headers per the contract.
3. **`PortalRequestForm.tsx`** new required fields + the group-size rule. Test: 202 body shape matches US-13a's DTO; group→size-required; consent+CAPTCHA gates preserved; generic error on failure.
4. **`TrackingLookup.tsx`** card. Test: renders status + own details only, never a resolved employee name/code; generic 404 message.
5. **`PortalPage.tsx`** card-grid + Log-in link. Test: three cards render; login links to the staff shell; no narrow-viewport horizontal scroll.
6. **`specs/traceability.md`** refresh. (Docs; no test.)

---

## Three questions

**1. What was the hardest decision in this plan?**
Whether to build the OTP wizard the prototype shows, or defer it. Building it would match the reference but ship a flow real visitors can't complete (no relay worker delivers the OTP), which contradicts US-13a's whole reason for making OTP config-gated — keep the portal working. Deferring the wizard and instead *fixing the now-broken direct-submit form* is the honest choice: it restores a working portal for real users today and leaves the OTP wizard for when delivery actually exists. The discovery that forced this was that US-13a's merge silently broke the existing form (new required fields) — so US-13b's first duty is a bug fix, not a redesign.

**2. What alternatives were rejected, and why?**
- **Full OTP wizard now (demo-only)**: rejected — ships a dead-end flow for real visitors until the relay worker exists; inconsistent with US-13a's config-gate.
- **Flag-aware wizard** (skip OTP when off): rejected for now — needs the frontend to learn the backend flag (a config endpoint or a build-time env var kept in sync), pushing beyond frontend-only scope for a step that still can't deliver anything.
- **Pixel-matching the prototype** (SVG illustration, custom fonts): rejected — more work, introduces styling the app doesn't use elsewhere; a plain grid matches the structure that matters.
- **Leaving CORS out** (frontend-only purity): rejected — without it the browser can't reach the API at all, so the UI is untestable in a real browser; re-applying an already-reviewed, orphaned fix is the pragmatic call, clearly fenced as an enabling change.

**3. What's the least confident part of this plan?**
Bundling the CORS backend fix and the traceability docs into a nominally frontend story. Both are justified (CORS is a prerequisite for browser-testing this UI; traceability was explicitly deferred to this branch), but they widen the story's surface beyond `apps/web`, and a reviewer may prefer the CORS fix as its own tiny Quick-Flow change (it qualifies: ≤3 files, no state-machine/tenancy/consent impact) rather than riding in here. Flagged so the human can split it out at Gate 1 if they'd rather.
