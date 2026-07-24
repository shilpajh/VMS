# US-13b: Portal UI Redesign (card layout + OTP wizard + tracking lookup)

Status: Approved (Human Gate 1, 2026-07-24) — blocked on US-13a merging first

> Split from the original combined US-13 (see `docs/plans/US-13a.md` for the backend/security half and the split rationale). **US-13b is the frontend-only redesign and depends on US-13a being merged first** — it consumes the endpoints US-13a ships. Design reference: `visitor_management_prototype (1).jsx`'s `VisitorPortal` function and the live prototype screenshot.

## Part A — Intent

### Problem
US-11's portal is a single-page form (name/contact/host, one submit). The product design reference (prototype `VisitorPortal` + screenshot) is a multi-card landing page — **Request a visit** (a contact → OTP → details wizard), **Track a visit request** (status lookup by reference), and **Log in** (staff shell entry) — matching PRD 3.1's "look up live status on the same portal using [the tracking] reference, with no account needed." US-13a ships the backend for the OTP wizard and the tracking lookup; nothing yet renders them.

### Solution
Redesign `apps/web/src/portal` to the reference's card layout: a Request-a-visit multi-step wizard (contact + privacy consent → OTP request/verify → visit details) driving US-13a's `otp/request`/`otp/verify`/`visit-requests` endpoints; a Track-a-visit card driving the lookup endpoint; and a Log-in card linking into the existing MSAL staff shell. Server decides everything; the UI only renders (`frontend-react.md`).

### Out of scope (explicit scope-creep fence)
- **All backend/API/contract work** — US-13a. This story adds no endpoints and changes no server behavior.
- **Feedback widget & downloadable user manual** (present in the prototype) — no PRD grounding, no backend; not built. The prototype's Feedback card would need its own collection/retention/consent story; the manual-download is cosmetic. Deliberately dropped.
- **Real ID/selfie file upload** — the wizard renders the `identity_verification_choice` radio (upload-now vs send-to-host) as US-13a's inert intent enum only; no actual file picker that stores/transmits a file (US-03 territory). The prototype's file-drop UI is represented as the choice, not a working uploader.
- **Group-member entry UI** — renders `group_type` + `expected_group_size` (a count) per US-13a; does not build a per-member repeater form.
- **Consuming/displaying the check-in code in the tracking card** — US-13a's lookup never returns it; the card shows status + the visitor's own submitted details only, matching that contract (a deliberate divergence from the prototype, which shows the code).

### Risks (non-obvious failure modes)
- **The wizard's client-side step state is not a security control.** US-13a's server-side token validation is. The UI must not assume its own `step === "verified"` means anything to the backend — it always sends the token US-13a issued and lets the server decide (a modified client that skips steps just gets a 422).
- **Demo vs. real OTP delivery.** With US-13a's `portal_otp_required` flag and no relay worker, a real deployment can't deliver the OTP yet. The wizard must degrade honestly: when the flag is off (backend doesn't require a token), the wizard should still function end-to-end; the "enter the code we sent you" copy must not imply a message was actually delivered in an environment where it wasn't. Coordinate the exact copy/flag-awareness with US-13a's config.
- **Anti-enumeration is a backend property, but the UI must not re-leak it.** Every non-OK response (400/404/422/429/network) must render one identical generic message, exactly as US-11's form already does — the redesign must preserve that, not regress it by rendering distinguishable per-status errors.
- **WCAG on a multi-step wizard** — focus management across steps (moving focus to the new step's first field/heading), labeled inputs, `role="alert"`/`role="status"` live regions, keyboard-only completion — the same standard US-01's `CheckinPage` had to meet, now across a 3-step flow.
- **First substantial multi-column responsive layout** in this app — the card grid must not break the page's horizontal scroll on mobile (the prototype uses a phone-frame preview; the real app is just responsive).

## Part B — Contracts
None. Frontend-only; consumes US-13a's already-approved OpenAPI contract. No state-machine, API, permission, or schema change originates here.

### Gherkin scenarios
```gherkin
Feature: Portal UI redesign (US-13b)

  Scenario: The wizard walks contact -> OTP -> details and shows the tracking reference
    Given I am on the acme-corp portal landing page
    When I acknowledge the privacy notice and enter my email and request an OTP
    And I enter the OTP and verify it
    And I fill in name, host, purpose, group type, identity-verification choice and submit
    Then I see the tracking reference returned by the server

  Scenario: Tracking card renders server status without leaking anything extra
    Given I have a tracking reference for an approved request
    When I enter it in the Track-a-visit card and check status
    Then I see the status the server returned and my own submitted details
    And I never see a resolved employee host name or a check-in code

  Scenario: Every failure renders one identical generic message (anti-enumeration preserved)
    Given the server returns 400/404/422/429 or a network error at any step
    Then the UI renders the same generic error each time, never a status-specific one
```

## Part C — Plan

### Definition of done
- All 3 Gherkin scenarios pass as Testing-Library tests.
- The wizard (`contact+consent → OTP → details`) drives US-13a's three endpoints with the correct request shapes (asserted against the OpenAPI contract types, not hand-rolled).
- Privacy-notice acknowledgment is required on the FIRST step (before OTP request), matching US-13a's consent ordering — a test asserts "Request OTP" is disabled/blocked until acknowledged.
- Every non-OK response at every step renders one identical generic message — directly tested across 400/404/422/network.
- The tracking card renders status + the visitor's own submitted details only, and a test asserts it never renders a field that would only exist if the server had returned a resolved employee name or a check-in code.
- WCAG 2.1 AA: each step's inputs are labelled; focus moves to the new step on transition; success/error use `role="status"`/`role="alert"`; the whole flow is keyboard-completable — tested.
- All user-facing strings via `t()` (i18next); no hardcoded copy.
- The Log-in card links into the existing MSAL staff shell (no auth code change).
- The OTP-delivery copy is honest under US-13a's `portal_otp_required` flag (no "we sent you a code" claim when nothing was delivered) — coordinated with the flag's state.
- `tsc -b` and `oxlint` clean; no `apps/web/src/portal` horizontal-scroll regression on a narrow viewport.

### File map (frontend only — apps/web/src/portal)
- `PortalPage.tsx` — amend: card-grid layout (Request a visit / Track a visit / Log in), replacing the single-form page.
- `PortalRequestForm.tsx` — amend: multi-step wizard shell + the details step (adds purpose/group_type/expected_group_size/identity_verification_choice fields).
- `ContactConsentStep.tsx` — new: step 1 (contact + privacy-notice acknowledgment + Request OTP).
- `OtpStep.tsx` — new: step 2 (OTP request feedback + verify).
- `TrackingLookup.tsx` — new: the Track-a-visit card.
- Tests: `PortalRequestForm.test.tsx` (amend), `ContactConsentStep.test.tsx`, `OtpStep.test.tsx`, `TrackingLookup.test.tsx` (new).
- Possibly a small shared `portalApi.ts` — typed fetch wrappers for the three endpoints (keeps request shapes in one place, matching the contract).

### User journey (demo path)
As US-13a's journey, but driven through the redesigned browser UI instead of curl: land on the card page → consent + request OTP (step 1) → verify OTP (step 2, code recovered from the outbox in demo) → fill details + submit (step 3) → see tracking reference → paste it into the Track card → see status.

### Numbered tasks
1. **`portalApi.ts`** typed wrappers for `otp/request`/`otp/verify`/`visit-requests`/lookup. Test: correct URLs/bodies/headers.
2. **`ContactConsentStep.tsx`** (step 1, consent-gated Request-OTP). Test: OTP request blocked until privacy-ack; generic error on failure.
3. **`OtpStep.tsx`** (step 2). Test: verify success advances; every failure renders the one generic message.
4. **`PortalRequestForm.tsx` wizard shell + details step** (new fields). Test: full walk to a rendered tracking reference; focus moves per step.
5. **`TrackingLookup.tsx`** card. Test: renders server status + own details only; never a resolved employee name/code; generic 404 message.
6. **`PortalPage.tsx` card-grid layout** + Log-in card link. Test: renders three cards; login links to the staff shell; no mobile horizontal-scroll regression.

---

## Three questions

**1. What was the hardest decision in this plan?**
Whether the wizard's "we sent a code to your phone/email" copy is honest given US-13a's `portal_otp_required` flag defaults off and no relay worker delivers anything yet. Rendering a confident "code sent" message in an environment where no message was sent is a small but real integrity issue (the OS's own communication-honesty guardrail applied to end users). Resolved by making the copy flag-aware / demo-honest rather than asserting delivery unconditionally — but it's the part most coupled to US-13a's runtime config.

**2. What alternatives were rejected, and why?**
- **Building the Feedback and manual-download cards** to match the prototype pixel-for-pixel: rejected — no PRD requirement and (Feedback) no backend; a faithful build would need its own retention/consent design disproportionate to a decorative card.
- **A working ID/selfie file uploader**: rejected — US-03 territory; storing/transmitting an identity document is a large privacy story, not a portal-redesign detail. Rendered as the inert choice US-13a models.
- **Showing the check-in code in the tracking card (prototype behavior)**: rejected to match US-13a's contract, which deliberately never returns it.
- **One monolithic `PortalRequestForm` holding all three steps inline**: rejected in favor of extracted `ContactConsentStep`/`OtpStep` components — each step is substantial (validation, error states, live regions) and easier to test in isolation, mirroring how US-01 extracted `getAccessToken`.

**3. What's the least confident part of this plan?**
Whether the card-grid layout should faithfully reproduce the prototype's exact two-panel (illustration + cards) composition or adopt a simpler responsive grid that fits the existing app's plainer visual language. The prototype is richly styled (SVG illustration, specific fonts); US-11's current portal is deliberately minimal. Matching the prototype exactly is more work and introduces styling the rest of the app doesn't use; a plainer grid is faster but visibly less polished than the reference the user pointed at. This is a fidelity-vs-effort call a human may want to weigh in on at Gate 1.
