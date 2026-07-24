# ADR-004: Portal Contact Verification (OTP) and Tracking-Status Lookup

## Status
Proposed

## Context
US-13a adds three new anonymous, unauthenticated-facing portal endpoints — OTP request, OTP verify, and tracking-status lookup — plus a new credential class (the OTP and a derived verification token). This changes the public portal's security posture and adds an event contract, both AGENTS.md ADR triggers. `.claude/rules/security-privacy.md` treats an unauthenticated portal surface without specified rate limiting AND bot/abuse protection as a Blocking gap. Two independent design-gate cold reads (domain-architect, security-privacy-reviewer; `docs/reviews/US-13-review.md`) produced four Blocking findings and seven Should-fix items; this ADR records the decisions that resolve them.

## Decision

### 1. Four Gate-1 human decisions (the Blocking findings)
- **OTP requirement is config-gated** (`settings.portal_otp_required`, default OFF). When off, the portal keeps US-11's exact behavior (no verification token required); when on, submission requires a validated token. Rationale: OTP delivery needs an SMS/email relay worker that ADR-002 explicitly does not build (deferred twice already). Making a not-yet-deliverable OTP a *mandatory* precondition would break the working portal — so the mechanism is built and tested but not mandatory until the relay exists. (Resolves domain-architect B2.)
- **Tracking lookup returns status + the visitor's OWN submitted details only.** `{status, visitor_full_name, host_hint}` where `host_hint` is the string the visitor typed — NEVER the resolved employee's `display_name`, NEVER a check-in code. Returning the resolved employee name would leak employee PII to an anonymous caller AND create a host-roster enumeration oracle (submit with a guessed host, look up the reference, learn populated-vs-empty), reversing US-11's deliberate "host resolution never branches the response" anti-enumeration design. (Resolves security-privacy-reviewer B2.)
- **Consent moves ahead of the OTP request.** `privacy_notice_acknowledged` + `privacy_notice_version` are required at `otp/request` — the point `contact_value` (PII) is first stored and dispatched to a vendor — captured on the `portal_contact_verifications` row and copied onto the visit at submission. (Resolves domain-architect B1 / security-privacy-reviewer Should-fix #7.)
- **Bot/abuse protection is specified per endpoint.** CAPTCHA (Turnstile, reusing US-11's verifier) runs before any DB work on `otp/request` and `otp/verify`. Tracking lookup gets a dedicated, tighter rate-limit bucket (its own Redis namespace) plus the ~40-bit unguessable reference as the anti-guessing control — CAPTCHA on a status check is poor UX, so this is the "equivalent" control the guardrail permits. (Resolves security-privacy-reviewer B1.)

### 2. OTP as a keyed-HMAC-hashed, superseding, attempt-capped, constant-work-verified credential
- **6-digit OTP** (`secrets.randbelow(10**6)`), **keyed HMAC-SHA256** at rest (`app/crypto/hmac_hash.py`), never bare SHA-256: a 6-digit value has only 10⁶ preimages and a bare hash would be instantly reversible if leaked. The check-in code (US-01) could bare-hash only because it is ~192 bits. (Should-fix #3.)
- **Supersede on reissue**: a fresh `otp/request` for the same `(tenant, contact_channel, contact_value)` sets `superseded=true` on prior unconsumed rows, and verify resolves against exactly the single current row — so the 5-attempt cap is per-contact, not per-row (else N resends → 5N guess budget). (Should-fix S1/#2.)
- **Constant-work verify**: no-pending-OTP / wrong-code / expired / exhausted all run the same SELECT + one attempt-increment UPDATE (a sentinel id for the no-usable-row case) + one HMAC compare — closing the work-differential timing oracle that would otherwise reveal whether a contact has a pending OTP. (Should-fix #4.)
- **Brute-force math**: with the per-contact OTP-request cap (3 per ~5-min window) and the 5-attempt cap, an attacker gets ≈15 live guesses per contact per window against a 10⁶ keyspace — negligible. Concrete thresholds live in `app/config.py`, tunable without a code change.

### 3. Verification token: single-use, contact-scoped, dedup-before-consume
`secrets.token_urlsafe(24)`, HMAC-hashed at rest, bound to the exact `(tenant, contact_channel, contact_value)` it was issued against, consumed via a race-safe guarded UPDATE (affected-row check) on submission. **A verified contact proves channel control, NOT visitor identity** — no downstream story or host-notification wording may treat a token-backed request as identity-assured (identity verification is US-03 territory). Submission runs the `Idempotency-Key` dedup check BEFORE consuming the token, so a legitimate idempotent retry returns the existing tracking reference rather than 422-ing on an already-spent token. (Should-fix S3.)

### 4. OTP dispatch reuses the outbox, with an OTP-specific send-gate
`portal.otp.dispatch` (message_type) reuses `outbox_messages`, **envelope-encrypted** (carries `contact_value` PII + the plaintext OTP — same sensitivity as `visit.checkin_code.dispatch`; routed through `encrypt_payload` → `payload`/`payload_key_ref`, no plaintext at-rest path). `aggregate_type = "portal_contact_verification"`, `aggregate_id = verification_id`, `not_valid_after = otp_expires_at`. Idempotency key `sha256("portal.otp.dispatch:" + verification_id)` uses a fresh UUID per request so a legitimate resend re-dispatches (unlike the one-per-visit check-in-code key). The relay worker's send-gate (ADR-002 §4, adapted to this non-`visits` aggregate) must refuse to deliver a `superseded`, expired, or `consumed_at` row. Delivery itself is the not-yet-built relay worker's job. (Should-fix S2.)

### 5. `group_type` + `expected_group_size` for muster visibility
`group_type` (`individual`/`group`) is captured with `expected_group_size` (required when `group`) so a group visit's head-count is visible to muster/`Safe` accounting even though per-member visitor records and a group-credential model are a later story. A `group` visit currently represents one tracked person; its other members remain invisible to per-person muster — a named limitation for whoever builds evacuation mustering. (Should-fix S6.)

### 6. Audit and retention
- **PII-free audit** (`app/domain/portal/otp.py`): `portal.otp.verified` and `portal.otp.attempts_exhausted` events are written in the domain layer, anchored on the verification row's UUID (never `contact_value` or the OTP) — abuse (bombing, brute-force exhaustion) is forensically visible without PII in the append-only `audit_events` table (same discipline US-11 applied to `denial_reason`). (Should-fix S7.)
- **Retention**: `portal_contact_verifications` holds `contact_value` PII; only successful submission deletes rows (token consume). Abandoned/expired rows must be purged by the ops-role retention job (US-07). This store is registered with the same standing PII-purge GA gate as `visits`/`outbox_messages`, plus an abandoned/expired-row TTL cleanup. `vms_app` has a DELETE grant on this table (unique among tenant tables) for the token-consume path. (Should-fix S4/#6.)

## Consequences

**Benefits**
- The working portal is never broken (config-gate), while the full OTP mechanism is built and tested.
- The OTP credential gets protection proportional to its low entropy (keyed HMAC + supersede + attempt cap + constant-work verify + strict per-contact rate limit).
- Anti-enumeration holds across all three new surfaces, and employee PII is never exposed to an anonymous caller.
- The dispatch reuses ADR-002's encryption/retention/never-log discipline for free — no new vendor-abstraction code.

**Limitations / out of scope**
- No SMS/email relay worker (deferred, ADR-002); this story writes dispatch intent only. In demo, the OTP is recovered by decrypting the outbox row.
- `identity_verification_choice` is an inert enum (no file stored/transmitted); neither value has a downstream effect yet.
- A `group` visit has no per-member records; muster sees the head-count, not the individuals.
- OTP-request→visit correlation is intentionally broken (the token is deleted on consume; no `verification_id` is persisted on the visit), which limits abuse investigation to the PII-free audit events; a masked linkage is a future option if needed.

**Operational impact**
- New Alembic migration for `portal_contact_verifications` (RLS enable+force, two indexes, `vms_app` DELETE grant), tested `downgrade()`.
- A Key-Vault-managed HMAC secret (`otp_hmac_key_ref`) + a retention/purge job for abandoned rows (US-07).
- New dedicated Redis rate-limit key namespaces for the OTP and lookup surfaces.

## Security and privacy impact
- **Tenant isolation**: `portal_contact_verifications` is tenant-scoped with FORCE RLS (`USING`+`WITH CHECK`, fail-closed GUC) exactly per ADR-001; tenant context is set from `tenant_slug` before any row is written, even though a row precedes any visit.
- **Credentials at rest**: OTP and verification token exist at rest only as keyed HMACs; the plaintext OTP lives only inside the envelope-encrypted dispatch payload.
- **PII**: `contact_value` is never logged, never in `audit_events`, envelope-encrypted in the dispatch payload, and purged (consume-delete + abandoned-row TTL). This retention window is a placeholder pending real DPDP compliance sign-off (same standing gate as US-11).
- **Anti-enumeration**: uniform responses on all three surfaces (generic 202 on OTP request; uniform 400 on verify; byte-identical 404 on lookup); tracking lookup never exposes the resolved employee name or a check-in code.
- **No automated denial / biometric / watchlist path** in this story (confirmed).
- **Secrets**: the HMAC key and envelope key live in Key Vault / managed identity only — never in code, fixtures, prompts, or logs.

### Open questions surfaced to the orchestrator/human (not silently resolved)
- **O1 — Rate-limit thresholds are first-cut** values without production traffic to calibrate; config-driven so they can be tuned. A human may want stricter per-contact limits before real abuse.
- **O2 — Retention windows are placeholders** pending DPDP sign-off (inherits US-11's standing gate); the abandoned-row TTL cleanup job is US-07's to build.
- **O3 — Relay worker** for OTP delivery is a hard prerequisite before `portal_otp_required` can be turned on in any real environment.
