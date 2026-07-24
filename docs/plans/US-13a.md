# US-13a: Portal OTP Contact Verification + Tracking-Status Lookup (backend)

Status: Approved (Human Gate 1, 2026-07-24)

> Split from the original combined US-13 per the design-gate review (file count > `/execute-story`'s 25-file guardrail; security-critical backend should not be reviewed in the same pass as a cosmetic UI redesign). **US-13a is this backend/contracts story; US-13b is the portal UI redesign and depends on US-13a.** Full reviewer findings: `docs/reviews/US-13-review.md`.

## Part A — Intent

### Problem
PRD Section 3.1 requires the public visitor portal to (a) verify the visitor controls the contact channel they submit, (b) capture "purpose of visit, and group size/type (individual or group)," and (c) let a visitor "look up live status — pending, approved, or denied — on the same portal using [the tracking] reference, with no account needed." US-11 built none of these: it captures name/contact/host with no contact-ownership proof, no purpose/group fields, and ships no lookup endpoint (all explicit, documented US-11 scope cuts; `docs/reviews/US-11-review.md` flagged the lookup follow-up as needing "its own entropy and rate-limiting" work). Anyone can currently submit a request naming any third party's phone/email as the visitor's own contact_value.

### Solution
- Add OTP-based contact verification as a precondition to portal submission: request an OTP for a `contact_channel`/`contact_value`, verify it, receive a short-lived single-use verification token, then submit carrying that token. **Gated behind a config flag (`portal_otp_required`, default OFF)** — see the Relay-worker decision below — so the working US-11 submission path is never broken while the SMS/email relay worker doesn't exist.
- Add `GET .../visit-requests/{tracking_reference}` for no-account status lookup, returning **only status + the visitor's own submitted details** (never the resolved employee host's canonical name) — the deferred US-11 follow-up, done with the entropy/rate-limit/anti-enumeration analysis its review demanded.
- Add the PRD-required `purpose`, `group_type` (+ `expected_group_size`), and `identity_verification_choice` fields to the submission DTO/model.

### Human decisions taken at Gate 1 (from the design-gate review's Blocking findings)
1. **Relay-worker / OTP gate → config-gated.** OTP verification is *required to submit only when `portal_otp_required` is on*. Default OFF: the portal keeps working exactly as US-11 today; the OTP mechanism is fully built and tested but not mandatory until the (separate, not-yet-built) relay worker can deliver codes. Resolves domain-architect B2.
2. **Tracking lookup exposure → status + visitor's own submitted details only.** Returns `{status, visitor_full_name, host_hint}` — where `host_hint` is the string the visitor *typed*, NEVER the resolved employee's `display_name`. Closes the host-roster enumeration oracle and the employee-PII disclosure. Resolves security-privacy-reviewer B2.
3. **Consent ordering → privacy notice moves ahead of OTP request.** `privacy_notice_acknowledged` + `privacy_notice_version` are captured and required at `otp/request` (the point contact PII is first processed and dispatched to a vendor), stored on the verification row, and copied onto the visit at submission. Resolves domain-architect B1 / security-privacy-reviewer Should-fix #7.
4. **Bot/abuse protection → specified per endpoint** (resolves security-privacy-reviewer B1): CAPTCHA (Turnstile, reusing US-11's verifier) on `otp/request` and `otp/verify`; a dedicated, tighter rate-limit bucket (not the shared submission pool) plus the high-entropy unguessable reference as the anti-guessing control on tracking lookup (CAPTCHA on a status check is poor UX — the equivalent control per the guardrail).

### Out of scope (explicit scope-creep fence)
- **Portal UI redesign** — US-13b. This story ships only the API + contracts; existing `PortalRequestForm.tsx` is untouched here.
- **The SMS/email relay worker itself** — still deferred (ADR-002). This story writes only the `portal.otp.dispatch` outbox intent. In demo, the OTP is recovered by decrypting the outbox row (as US-01's walkthrough did).
- **Real ID/selfie upload/storage/OCR** — `identity_verification_choice` is an inert intent enum only; no file is ever stored or transmitted. (US-03 territory.)
- **Group-visitor member fan-out** — `group_type`/`expected_group_size` are captured (so muster head-count isn't blind — see Risks), but this story does not create per-member visitor records or a group credential model; that's a separate design question.
- **Returning the check-in code via tracking lookup** — deliberately never, unlike the prototype. A check-in code is a bearer credential (ADR-002, US-01); lookup returns status only. A considered, security-motivated divergence.
- **Feedback widget / manual download** — no PRD grounding; not built (US-13b won't build them either).
- **`/biometric-provider-poc`** — N/A: OTP/SMS/email delivery is not biometric/OCR/access-control/CCTV. Flagged so it's not mistaken for an overlooked gate.

### Risks (non-obvious failure modes)
- **The OTP and the verification token are two bearer-credential classes** needing the same discipline as US-01's check-in code: short expiry, hashed at rest, single-use, generic errors, rate-limited on every step.
- **A 6-digit OTP is low-entropy (10⁶).** Copying the prototype's 4-digit demo code literally (10⁴) would be dangerously guessable. This plan uses 6 digits, and — critically — the primary defense is a **5-attempt-per-OTP cap plus a per-contact OTP-request cap plus supersede** (below), not the keyspace alone. `otp_hash` is **HMAC-SHA256 under a Key-Vault-managed key**, NOT bare SHA-256: a 6-digit value has only 10⁶ preimages and would be instantly reversible from a leaked plain hash — the check-in-code precedent used a bare hash only because that credential is ~192 bits (US-11 review Should-fix #4 recorded this exact distinction).
- **Multi-OTP / resend must supersede.** A fresh `otp/request` for the same `(tenant, contact_channel, contact_value)` invalidates any prior unconsumed OTP rows for that tuple, so exactly one "current" OTP exists per tuple and the 5-attempt cap is truly *per-contact*, not *per-row* (else N resends → 5N guess budget).
- **`otp/verify` must be constant-work.** "No pending OTP" (a SELECT that finds nothing) vs. "wrong code" (SELECT + attempt-increment UPDATE) is a timing/behavior oracle revealing whether a contact has a pending OTP — the same class `backend-python.md`'s rule and US-01 call out. The verify path always performs the same query shape + an HMAC compare (against a fixed dummy hash when no row exists) so the four failure causes (no OTP / wrong / expired / exhausted) are indistinguishable by timing, not only by body.
- **Client-side "verified" state is never trusted.** The security boundary is the server validating an opaque single-use token at submission time, not the UI's step sequence.
- **Tracking lookup is a new anonymous read surface.** Mitigated to near-nothing by decision 2: a correct-guess reveals only status + details the guesser already typed. Still gets its own dedicated rate buckets (not the shared submission pool, which would let a lookup flood starve legitimate submissions).
- **OTP-request spends vendor money and delivers to an arbitrary third party.** Needs CAPTCHA + a strict per-contact bucket, or it's an OTP-bombing / contact-enumeration surface.
- **`portal_contact_verifications` is a new PII (`contact_value`) store.** Only the happy path deletes rows; abandoned/expired ones must be purged (registered with the standing retention gate + a TTL cleanup), or PII accumulates.

## Part B — Contracts

### ADRs
**ADR-004 — Portal contact verification (OTP) and tracking-lookup contract** (new). Trigger: changes the public portal's security posture (new anonymous-facing credential class + new anonymous read surface) and adds an event contract — AGENTS.md ADR triggers. Records: the four Gate-1 decisions above and their rationale; OTP/token entropy, lifetime, HMAC-hash, supersede, and constant-work-verify parameters and why they diverge from the prototype's demo values; the OTP dispatch send-gate mapping onto a non-`visits` aggregate; the tracking-lookup anti-enumeration + dedicated-bucket design; why the check-in code is never returned by lookup; and — explicitly — that **a verified contact proves channel control, NOT visitor identity** (so no downstream story or host-notification wording treats a token-backed request as identity-assured).

### Statemachine impact
None. OTP verification is a submission precondition (analogous to the CAPTCHA check that already runs before any DB work in `app/api/portal.py`), not a `visit-lifecycle.yaml` guard. A visit still enters at `Requested`. `visit-lifecycle.yaml` is untouched.

### New table: `portal_contact_verifications` (tenant-scoped, RLS enable+force per ADR-001, reused verbatim)
Columns: `id` (UUID PK, = the `verification_id`), `tenant_id` (FK, indexed, RLS), `contact_channel`, `contact_value` (PII), `otp_hash` (HMAC-SHA256, hash-only at rest), `otp_expires_at` (+5 min), `otp_attempts` (int, default 0, cap 5 enforced in-domain), `superseded` (bool, default false — set true when a newer request for the same tuple arrives), `privacy_notice_acknowledged` (bool), `privacy_notice_version` (string — captured here now, per consent decision), `verification_token_hash` (nullable HMAC until OTP verified), `verification_token_expires_at` (nullable, +15 min once set), `consumed_at` (nullable — set when the token is spent on a submission), `created_at`. Indexes: `(tenant_id, contact_channel, contact_value)` for the verify/supersede path; `verification_token_hash` for the submission path. No visitor name captured at this stage.

### API contract delta (`packages/contracts/openapi/visits.yaml` amendments)
- `POST /public/portal/{tenant_slug}/otp/request` — body `{contact_channel, contact_value, privacy_notice_acknowledged, privacy_notice_version, turnstile_token}`. Order (same discipline as submission): CAPTCHA → rate-limit → tenant-resolve → privacy-ack gate → supersede prior rows → create row + `portal.otp.dispatch` outbox (atomic). Dedicated rate buckets: **per-IP capacity 5 / refill 1·min⁻¹; per-contact_value capacity 3 / refill 0.2·min⁻¹ (≈1 per 5 min)** — stricter than submission's 10/5. Always `202` + generic body regardless of whether the contact had a prior OTP or is a known user (anti-enumeration). `422` if privacy-ack missing/false; `400` on CAPTCHA failure.
- `POST /public/portal/{tenant_slug}/otp/verify` — body `{contact_channel, contact_value, otp_code, turnstile_token}`. Constant-work path. `200` + `{verification_token}` (plaintext, transient) on success; one uniform `400` for every failure (no pending OTP / wrong / expired / attempts-exhausted). Dedicated buckets: **per-IP capacity 10 / refill 2·min⁻¹** (the real defense is the 5-attempt-per-OTP cap). `400` on CAPTCHA failure.
- `POST /public/portal/{tenant_slug}/visit-requests` (amend) — `PortalVisitRequestCreate` gains `purpose` (required), `group_type` (enum `individual`/`group`, required), `expected_group_size` (int, required when `group`, else null), `identity_verification_choice` (enum `upload_now`/`send_to_host`, required — inert flag), and `verification_token` (**required only when `portal_otp_required` is on**; optional otherwise). Ordering: CAPTCHA → rate-limit → tenant-resolve → **Idempotency-Key dedup (return existing if match)** → **then** validate+consume `verification_token` (when present/required) → create visit. Dedup-before-consume so a legitimate idempotent retry returns the existing reference instead of 422-ing on an already-spent token. The token must match a non-expired, non-consumed `verification_token_hash` row for the SAME `(tenant, contact_channel, contact_value)` as the submission, is consumed atomically (guarded delete/update + affected-row check, race-safe), and the visit copies `privacy_notice_version` from that row. When `portal_otp_required` is off and no token is supplied, the endpoint keeps US-11's behavior (DTO's own `privacy_notice_acknowledged`/`version` gate). Missing/invalid/expired/mismatched token (when required) → uniform `422`, no visit created. New `visits.contact_verified` bool records whether the visit was created via a validated token (a non-PII trust property).
- `GET /public/portal/{tenant_slug}/visit-requests/{tracking_reference}` — new. Tenant-scoped by slug (`resolve_public_tenant`). Dedicated rate buckets (**per-IP capacity 20 / refill 5·min⁻¹; per-tenant capacity 120 / refill 60·min⁻¹** — separate Redis key namespace from submission). Returns `{status, visitor_full_name, host_hint}` on match — `host_hint` is the visitor's typed string, **never** the resolved employee name; **never** the check-in code. Byte-identical uniform `404` for unknown reference / wrong tenant / malformed input.

### Event contract (new): `packages/contracts/asyncapi/portal-otp-dispatch.yaml`
Reuses `outbox_messages` (message_type `portal.otp.dispatch`), **envelope-encrypted** (payload carries `contact_value` PII + the plaintext OTP — same sensitivity class as `visit.checkin_code.dispatch`; routed through `encrypt_payload` → `payload`/`payload_key_ref`, no plaintext at-rest path). `aggregate_type = "portal_contact_verification"`, `aggregate_id = verification_id`, `not_valid_after = otp_expires_at`. `idempotency_key = sha256("portal.otp.dispatch:" + verification_id)` — fresh UUID per request (non-deterministic on contact, so a legitimate resend re-dispatches; preserves ADR-002 one-row-one-key redelivery idempotency). **OTP-specific send-gate** (extends ADR-002 §4, which assumes a `visits` row): the relay worker must refuse to deliver — marking the row `failed` — if the source `portal_contact_verifications` row is `superseded`, past `otp_expires_at`, or already `consumed_at`. Never log the decrypted payload.

### Audit (new, PII-free)
`portal.otp.verified` and `portal.otp.attempts_exhausted` audit events (actor=`portal`, target = the verification row UUID, coded reason) — **never** `contact_value` or the OTP (same purge-exempt-append-only discipline US-11 applied to `denial_reason`). `visit.requested` is unchanged in shape; the new `visits.contact_verified` bool carries the verified-trust property queryably without PII in the audit row.

### Gherkin scenarios
```gherkin
Feature: Portal OTP verification and tracking lookup (US-13a)

  Scenario: Full happy path — request OTP (with consent), verify, submit, track
    Given portal_otp_required is on for tenant "acme-corp"
    When I acknowledge the privacy notice and request an OTP for email "jane@example.com"
    And I verify that OTP correctly and receive a verification token
    And I submit a request for "Jane Visitor" with that token, host_hint "Rahul", purpose "Business meeting", group_type "individual"
    Then the response is 202 with a tracking_reference
    When I look up that tracking_reference
    Then the response is 200 with status "Requested", visitor_full_name "Jane Visitor", host_hint "Rahul"
    And the response contains no check-in code and no resolved employee name

  Scenario: OTP fails after 5 attempts, and a resend supersedes the old code
    Given I requested a valid OTP for phone "+91-9000000000"
    When I submit 5 incorrect OTP codes
    Then each returns the same generic 400
    And a 6th attempt with the CORRECT (now-superseded) code also returns 400
    And requesting a NEW OTP invalidates the old row and lets me verify the fresh code

  Scenario: A consumed verification token cannot be replayed (incl. concurrently)
    Given I verified an OTP and its token was already consumed by one submission
    When I submit again with the same token
    Then the response is 422 and no second visit is created
    And two concurrent submissions with the same fresh token yield exactly one 202 and one 422

  Scenario: Tracking lookup is uniform across every non-match cause, and host-name is never leaked
    Given tenant "acme-corp" has no visit with reference "REQ-000000000000"
    And tenant "globex" HAS a real visit whose host_hint resolved to a real employee
    When I look up "REQ-000000000000" at "acme-corp"
    And I look up globex's real reference while on "acme-corp"'s portal
    Then both responses are 404 with an identical body
    And no lookup response ever contains a resolved employee display_name
```

## Part C — Plan

### Definition of done
- All 4 Gherkin scenarios pass as executable tests.
- OTP is 6 numeric digits (`secrets.randbelow(10**6)`, zero-padded), **HMAC-SHA256** hashed under a Key-Vault-managed key at rest, never logged, never in any API response.
- A fresh `otp/request` sets `superseded=true` on all prior unconsumed rows for the same `(tenant, channel, contact_value)`; `otp/verify` resolves against the single current (non-superseded, non-expired) row only — directly tested (5N-budget regression: N resends still only ever allow 5 live attempts against the current code).
- `otp_attempts` enforced via a race-safe guarded increment-then-check capped at 5; the 5th and every later attempt return the identical generic 400 as a first wrong attempt.
- `otp/verify` is constant-work across no-OTP / wrong / expired / exhausted — a test asserts the same query+compare shape runs in all four (no early-return that skips the attempt UPDATE).
- CAPTCHA (Turnstile) verified before any DB work on both `otp/request` and `otp/verify`; the three new endpoints each use their own dedicated rate-limit buckets with the concrete thresholds in Part B — directly tested, not assumed inherited, and NOT sharing submission's Redis keys.
- `verification_token` is `secrets.token_urlsafe(24)`, HMAC-hashed at rest, single-use (race-safe atomic consume + affected-row check), scoped to the exact `(tenant, channel, contact_value)` it was issued against — a token for contact A cannot submit a request naming contact B.
- Submission ordering is dedup-check-*before*-token-consume — a test asserts an idempotent retry (same `Idempotency-Key`) returns the existing reference, not a 422.
- `portal_otp_required` gates the token requirement: off → US-11 behavior unchanged (a regression test proves the existing portal tests still pass with the flag off); on → token required (422 without it).
- Privacy-notice acknowledgment is required at `otp/request` (422 if absent) and its version is copied onto the visit at submission — tested end to end.
- Tracking lookup returns status + `visitor_full_name` + typed `host_hint` only; a test asserts the response never contains the resolved host's `display_name` nor any check-in code; and that unknown/wrong-tenant/malformed causes produce a byte-identical 404.
- `purpose`/`group_type`/`expected_group_size`/`identity_verification_choice` required-as-specified (422 otherwise; `expected_group_size` required iff `group_type=group`) and persisted; `visits.contact_verified` set correctly.
- `portal.otp.dispatch` outbox row is envelope-encrypted, uses the fresh-UUID idempotency key, maps `aggregate_type`/`aggregate_id`/`not_valid_after` per Part B, and is written atomically with the verification row.
- `portal.otp.verified` / `portal.otp.attempts_exhausted` audit events written, containing no `contact_value`/OTP.
- `portal_contact_verifications` registered with the standing PII-purge gate; an abandoned/expired-row TTL cleanup is specified (US-07 owns building the job) — documented, not silently uncovered.
- `0004_portal_contact_verification` migration has a tested `downgrade()`; `/confirm-schema` passes (tenant col + both indexes, RLS enable+force, grants, both new `visits` columns nullable/no-backfill).
- No secrets/PII/plaintext OTP/plaintext token in any log call site in this story's new code.

### File map

**Contracts**
- `packages/contracts/openapi/visits.yaml` — amend: 3 new/changed paths + `PortalVisitRequestCreate` new fields.
- `packages/contracts/asyncapi/portal-otp-dispatch.yaml` — new.
- `docs/architecture/adr/ADR-004-portal-contact-verification-and-tracking-lookup.md` — new.

**Backend (services/core-api)**
- `alembic/versions/0004_portal_contact_verification.py` — new: `portal_contact_verifications` (RLS enable+force, both indexes); `visits.purpose`/`group_type`(CHECK)/`expected_group_size`/`identity_verification_choice`(CHECK)/`contact_verified`(bool) — all nullable, no backfill. **Schema task — `/confirm-schema` inline.** Tested `downgrade()`.
- `app/models/portal_contact_verification.py` — new model.
- `app/models/visit.py` — amend: new columns.
- `app/domain/portal/otp.py` — new: generate (6-digit), HMAC hash, supersede, race-safe guarded-attempt verify (constant-work), token issue/consume. Dedicated module mirroring `tracking_reference.py`'s one-concern scope.
- `app/crypto/hmac_hash.py` — new (or extend `envelope.py`): keyed HMAC-SHA256 helper + Key-Vault-key-ref provider discipline, mirroring `envelope.py`'s Local/KeyVault split (local dev secret, never a real vault here).
- `app/api/dtos/visits.py` — amend `PortalVisitRequestCreate`; new `PortalOtpRequestCreate`, `PortalOtpVerifyRequest`, `PortalOtpVerifyAccepted`, `PortalTrackingStatus`.
- `app/api/portal.py` — amend: two new OTP routes; amend submission (token validate/consume, flag gate, dedup-before-consume, privacy-version-from-row); new tracking-lookup route.
- `app/security/rate_limit.py` — amend: parameterize key namespace + thresholds so the 3 new endpoints get independent buckets (reusing the existing Lua token-bucket primitive).
- `app/config.py` — amend: `portal_otp_required` (default False), the new bucket thresholds, `otp_hmac_key_ref`.
- `tests/` — new: `test_portal_otp_request.py`, `test_portal_otp_verify.py`, `test_portal_otp_attempts_and_supersede.py`, `test_portal_otp_verify_constant_work.py`, `test_portal_submission_verification_token.py`, `test_portal_submission_flag_off_unchanged.py`, `test_portal_tracking_lookup.py`, `test_portal_tracking_lookup_anti_enumeration.py`, `test_portal_otp_never_logged.py`, `test_migration_0004.py`.

**No frontend/kiosk/edge changes in this story** (US-13b owns the UI).

### User journey (demo path — with `portal_otp_required` on)
1. Anonymous visitor acknowledges the privacy notice + requests an OTP for their email → `202`; a `portal.otp.dispatch` outbox row is recorded (demo: decrypt it to read the OTP, as US-01's walkthrough recovered the check-in code).
2. Submits the OTP → `200` + a verification token (client-held only).
3. Submits name/host/purpose/group/identity-choice + token → `202` + tracking reference; `visits.contact_verified=true`.
4. Pastes the reference into lookup → `200`, status `Requested`, their own name + typed host string (no employee name, no code).
5. Host approves via the US-11 flow → `Registered`; lookup now shows `Registered`.
6. Re-submitting with the consumed token → uniform `422`.
7. Lookup of a made-up/cross-tenant reference → `404`, identical body.

### Numbered tasks
1. **`0004` migration** (new table + 5 new `visits` columns) — schema task, `/confirm-schema` inline, tested `downgrade()`. Test: RLS enable+force + both indexes; new columns nullable.
2. **Models** (`PortalContactVerification` + `Visit` amendment).
3. **HMAC helper** (`app/crypto/hmac_hash.py`) — keyed HMAC-SHA256, Local/KeyVault provider split. Test: deterministic under a fixed key; differs across keys; never logs the key.
4. **OTP domain module** (`app/domain/portal/otp.py`): generate/hash/supersede/constant-work-verify/token issue+consume. Test: correct code within cap succeeds; 5 wrong then correct both fail; supersede caps guesses per-contact not per-row; token single-use + contact-scoped + race-safe.
5. **OTP request/verify routes + DTOs + CAPTCHA + dedicated buckets.** Test: uniform 202/400; new buckets enforced independently; privacy-ack gate; no PII/OTP in logs.
6. **Submission amendment** (new fields, token validate/consume, flag gate, dedup-before-consume). Test: fields required-as-specified; token contact-scoped + consumed + replay-422 (incl. concurrent); flag-off leaves US-11 behavior unchanged; idempotent retry returns existing ref.
7. **Tracking-lookup route + DTO + dedicated buckets.** Test: 200 returns status + own details, never employee name, never code; unknown/wrong-tenant/malformed → byte-identical 404.
8. **ADR-004 + `portal-otp-dispatch.yaml` + audit events** — written alongside tasks 4–5 (where payload/audit shapes are decided).
9. **`/confirm-schema` final pass** across the new table + new `visits` columns, before `/verify-story`.

---

## Three questions

**1. What was the hardest decision in this plan?**
Whether OTP delivery should be a new synchronous vendor-adapter interface (like the Turnstile CAPTCHA call) or reuse the outbox+relay pattern (like `visit.checkin_code.dispatch`). CAPTCHA is a *verification* the request can't proceed without; an SMS/email *send* is a *notification* — the visitor is told "code sent" immediately and delivery latency is normal OTP UX. Reusing the outbox pattern means zero new vendor-abstraction code and it inherits ADR-002's encryption/retention/never-log discipline for free. The design-gate review confirmed this reuse is correct and buildable (no repeat of US-01's unencrypted-payload mistake), but also forced the config-gate decision: reusing a not-yet-built relay for a *mandatory* precondition would break the working portal, hence `portal_otp_required` defaulting off.

**2. What alternatives were rejected, and why?**
- **4-digit OTP (prototype's literal demo value)**: rejected — 10⁴ keyspace; widened to 6 digits with the 5-attempt cap + per-contact request cap + supersede as the actual defense.
- **Bare SHA-256 for `otp_hash`** (citing the check-in-code precedent): rejected — safe there only because that credential is ~192 bits; a 6-digit value is instantly reversible from a leaked plain hash. Uses keyed HMAC instead.
- **Returning the resolved host name / check-in code from lookup (prototype behavior)**: rejected — employee-PII disclosure + host-roster enumeration oracle (reverses US-11's anti-enumeration), and the check-in code is a bearer credential never exposed by any API. Lookup returns status + the visitor's own typed details only.
- **Making OTP a hard, always-on precondition**: rejected — breaks the working portal with no relay worker to deliver codes. Config-gated instead.
- **Reusing submission's rate buckets for lookup**: rejected — shared Redis keys let a lookup flood starve legitimate submissions. Dedicated buckets.
- **A bare `individual`/`group` flag with no size**: rejected as muster-blind — a `group` visit that tracks one person hides the rest from evacuation head-count. Captures `expected_group_size` (per-member identity still deferred, named explicitly).

**3. What's the least confident part of this plan?**
The concrete rate-limit numbers (per-IP 5/1·min⁻¹ and per-contact 3/0.2·min⁻¹ on `otp/request`, etc.) are defensible starting points that make the brute-force math check out (≈15 live guesses per contact per window against 10⁶), but they're first-cut values without production traffic to calibrate against — deliberately config-driven so they can be tuned without a code change, but a human may want different thresholds (e.g. stricter per-contact) before this faces real abuse. Flagged as the tunable-under-uncertainty part, not a proven-optimal one.
