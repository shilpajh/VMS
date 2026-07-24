# US-13 (Portal OTP verification, tracking lookup, redesign) — Design-Gate Review

Two independent pre-Gate-1 cold reads (domain-architect, security-privacy-reviewer) against `docs/plans/US-13.md`. Persisted here verbatim because the findings are too substantial to leave only in chat; dispositions and the human decisions they force are tracked in the plan's "Design-gate review disposition" section.

---

## domain-architect

### Blocking (require a human decision before approval)

**B1 — Consent captured *after* PII stored and an OTP dispatched.** The redesigned flow is contact → request OTP → verify → details, but `privacy_notice_acknowledged` stays on the submission (details) step. So `contact_value` (PII) is persisted to `portal_contact_verifications` and an SMS/email is dispatched to that contact *before* any privacy-notice acknowledgment. US-11 captured acknowledgment before any submission; this moves PII processing (store + outbound vendor message at tenant cost) ahead of consent. Human call: (a) accept with a rationale recorded in ADR-004, or (b) surface a lightweight notice/acknowledgment at the OTP-request step. Decide at Gate 1, not in verify-story.

**B2 — OTP is a hard precondition on submission, but no relay worker exists to deliver the OTP — so the working portal-submission path becomes non-functional in any real environment.** `verification_token` is required (422 if absent); the only way to create a `Requested` visit via the portal now runs through OTP verification, which needs an OTP the visitor never receives (relay worker deferred, twice already, by ADR-002/US-01). Unlike the additive `checkin_code.dispatch`/`arrival.notify` cuts, this puts a mandatory gate in front of a path that works today. Human call: sequence the relay worker as a hard prerequisite, config-gate the OTP requirement, or explicitly accept a demo-only portal until the relay lands.

### Should-fix
- **S1** — Multi-OTP/resend + attempt-cap interaction underspecified: does a new request supersede prior unverified rows, and which row does verify resolve against? 5-attempt cap is per-row; without supersede, N sends → 5N guess budget.
- **S2** — OTP dispatch reuses `outbox_messages` but doesn't define its send-gate/aggregate mapping; ADR-002 §4's gate assumes a `visits` row that doesn't exist here. Define `aggregate_type`/`aggregate_id` (`portal_contact_verification`/`verification_id`), `not_valid_after` = `otp_expires_at`, and an OTP-specific "don't deliver a superseded/expired OTP" gate.
- **S3** — `verification_token` consume vs. existing `Idempotency-Key` dedup: no stated ordering. Must be dedup-check-*before*-token-consume, or a legitimate idempotent retry 422s despite a visit existing.
- **S4** — `portal_contact_verifications` is a new `contact_value` PII store; only the happy path deletes rows. Abandoned/expired rows retain PII. Needs purge registration + abandoned-row TTL cleanup.
- **S5** — Reusing submission rate buckets for tracking lookup under-delivers the entropy/rate analysis US-11's review asked for; shared key = mutual budget exhaustion. Give lookup its own bucket; reconcile the 40-bit + PII-on-hit residual in ADR-004.
- **S6** — `group_type: "group"` with no size/member model is a *muster-safety* inconsistency (a `group` visit = one tracked person; other members invisible to `Safe`/head-count), not just deferred convenience. Capture an expected group size, or name the limitation explicitly for whoever builds muster.
- **S7** — No audit events for the OTP flow, and `visit.requested` doesn't record the new contact-verified trust property. Resolve explicitly (PII-free/masked references — `contact_value` must never enter `audit_events`, per the US-11 `denial_reason` discipline).

### Notes
- N1 — `identity_verification_choice` values are both inert this story; document no downstream effect.
- N2 — File count likely exceeds `/execute-story`'s 25-file guardrail (3 contracts + ~8 backend + ~8 tests + ~7 frontend). Consider splitting security-critical OTP/tracking backend from the cosmetic redesign — very different risk profiles.
- N3 — Specify indexes: verify queries `(tenant_id, contact_channel, contact_value)`; submission queries `verification_token_hash`.
- N4 — OTP-request→visit correlation is broken by design (token deleted, no `verification_id` on the visit); acceptable but limits abuse investigation.
- N5 — `_submission_dedup_key` doesn't include the new `purpose`/`group_type`; two submissions differing only there dedup to the first. Decide intentionally.

### Got right (don't lose in remediation)
Refusing to return the plaintext check-in code from lookup; OTP-as-second-bearer-credential framing (6-digit widening, 5-attempt cap, hashed, dedicated buckets); fresh-UUID-per-request idempotency key; verification-token bound to `(tenant, channel, contact_value)` + single-use; tenant-scoped RLS on the new table; no `visit-lifecycle.yaml` change.

---

## security-privacy-reviewer

Submission buckets confirmed: per-IP capacity 10 / refill 5·min⁻¹; per-tenant capacity 60 / refill 60·min⁻¹.

### Blocking

**B1 — Three new unauthenticated endpoints specify rate limiting but NO bot/abuse protection (CAPTCHA-or-equivalent) — a direct violation of the named public-portal guardrail, which lists "tracking lookup" by name.** `otp/request` is the highest-risk (spends money, delivers to an arbitrary third party; per-IP is IP-rotation-evadable, per-contact only protects one victim from repeat bombing, not volume across many victims). `otp/verify` is the online-brute-force surface. `GET .../visit-requests/{tracking_reference}` is named verbatim in the guardrail. "Same ordering discipline as CAPTCHA" is an ordering analogy, not a CAPTCHA check — none is wired. Per the rule's own text this is Blocking. Human may choose CAPTCHA on OTP endpoints + an equivalent abuse control (not a shared bucket) on lookup — but *some* per-endpoint bot control must be specified before the gate.

**B2 — Tracking lookup returns the resolved host's `host_display_name` to an anonymous caller: employee PII disclosure + a host-enumeration oracle, reversing US-11's deliberate anti-enumeration design.** US-11 makes host resolution *not branch the response* (unresolved `host_hint` → NULL `host_user_id` → byte-identical 202) precisely so a caller can't learn whether a guessed host name is real. Returning `host_display_name` at tracking time undoes that: submit with a guessed `host_hint`, look up the reference, learn populated-vs-empty → walk a name list → enumerate the tenant's host roster (each probe = one junk submission + one lookup, only shared-rate-limited). Independent verdict: **status-only is the correct default**, or at most echo the visitor's own submitted `host_hint` string, never the resolved employee `display_name`. `visitor_full_name` is lower-sensitivity but still PII against a bearer reference — same human privacy decision. Blocking pending that decision.

### Should-fix
1. **No concrete rate-limit numbers** for `otp/request`/`otp/verify` — the brute-force math can't be validated at the gate. Security rests on the per-`contact_value` OTP-request limit (≈ 5 × OTP-rows-per-contact-per-window vs. 10⁶). Specify numeric thresholds in Part B.
2. **OTP supersede rule unspecified** (same as dom-arch S1) — reissue must invalidate prior unconsumed rows; verify targets exactly the current one.
3. **Bare SHA-256 over a 6-digit OTP adds no attacker work** if the hash leaks (10⁶ preimages, instant offline). The check-in-code precedent was safe *because that credential is ~192 bits*. US-11 review Should-fix #4 already recorded this exact distinction. Use HMAC-SHA256 under a Key Vault key, or document accepted residual given expiry+cap+ephemeral+supersede.
4. **`otp/verify` work-differential timing oracle**: "no pending OTP" (SELECT only) vs. "wrong code" (SELECT + attempt-increment UPDATE) — bodies uniform, work isn't. Specify a constant-work verify path.
5. **Tracking lookup shares submission's Redis keys** → mutual budget exhaustion (lookup flood denies submissions). Give lookup its own buckets.
6. **`portal_contact_verifications` PII retention** (same as dom-arch S4) — register with erasure/purge; abandoned/expired rows aren't physically deleted.
7. **Contact PII collected/stored/transmitted before privacy-notice acknowledgment** (same as dom-arch B1) — DPDP consent-ordering gap; move acknowledgment ahead of `otp/request` or record lawful basis. Human compliance owner.

### Notes
- **Envelope encryption for `portal.otp.dispatch` is specified correctly and IS buildable — does NOT repeat US-01's mistake.** Payload routes through `encrypt_payload` → `payload`/`payload_key_ref` (NOT NULL); `otp_hash` is the only at-rest form on the verification row; plaintext OTP lives only inside the encrypted blob. Fresh-UUID idempotency key correct.
- Verification-token binding proves *contact control*, not *visitor identity* — correctly-scoped limitation; ADR-004 should say so explicitly so no downstream story treats a token-backed request as identity-assured.
- Single-use token consumption must be race-safe (atomic guarded delete + affected-row check); Gherkin covers sequential replay, not concurrent.
- No audit trail for OTP verify/consume/exhaustion; consider a PII-free (masked/hashed contact) audit event for abuse detection + DPDP accountability.
- No automated-denial/biometric/watchlist path (confirmed). Inherited standing gates (US-10/US-11 auth foundation, retention/consent GA gates) still apply.

**Disposition:** 2 Blocking (bot-protection; host-name exposure). 7 Should-fix (#3 HMAC agent-fixable; #6 retention + #7 consent → compliance-owner tracks). Envelope encryption correct. Approvable once both Blockings resolved and the concrete-numbers + OTP-supersede specification gaps are closed before implementation.
