# ADR-005: Retention Purge and Right-to-Erasure

## Status
Proposed

## Context
US-07 adds the DPDP-facing data-lifecycle mechanism: a time-based retention purge (delete/anonymize data past its retention window) and an on-demand right-to-erasure for a single data subject. This changes retention/residency behavior and security posture — both AGENTS.md ADR triggers — and performs the first *irreversible, cross-cutting, potentially cross-tenant* mutations in the system (a scheduled `DELETE`/anonymize sweep, and a per-subject cascade). Two design-gate cold reads (domain-architect, security-privacy-reviewer; `docs/reviews/US-07-review.md`) produced six Blocking findings; this ADR records the decisions that resolve them.

Two human constraints framed the whole design (from the Gate-1 decisions):
1. **Mechanism, not final policy.** The retention windows are placeholders, not ratified DPDP policy. The build makes each compliance decision a config/parameter change, not a rewrite, and surfaces every one for sign-off. US-07 does not close the DPDP GA gate.
2. **Human-gated production activation.** The mechanism is built and fully tested but does not run autonomously against production. A real run needs a compliance owner to flip an activation flag out-of-band; ops commands are dry-run by default.

## Decision

### 1. Tenant isolation is STRUCTURAL, not predicate-only — a dedicated `vms_purge` NOBYPASSRLS role (SP-B2)
The rejected first draft ran the purge as `vms_migrator` (BYPASSRLS) with "an explicit tenant predicate on every query" as the sole defense. For an *irreversible cross-tenant `DELETE`*, a behavioral test cannot prove the invariant, and a forgotten predicate is the exact missing-predicate class US-13a already hit — caught there only by a FORCE-RLS backstop that BYPASSRLS removes.

Instead, a new **`vms_purge`** role (`LOGIN`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, **`NOBYPASSRLS`**) runs the purge/erasure. It is *subject to* RLS+FORCE, and the purge sets `SET LOCAL app.current_tenant_id` (a per-tenant GUC) before each tenant's sweep. Postgres therefore structurally scopes **every** statement to that one tenant even when the query carries no explicit tenant predicate — a forgotten predicate cannot leak or destroy another tenant's data. This is proven by `test_structural_tenant_isolation` (predicate removed; the other tenant's row is untouched purely by RLS+GUC). It costs a new role, a session helper (`app/db/purge_session.py`), and a per-tenant GUC loop — the right price for an operation that cannot be undone. `vms_purge` holds exactly the grants it needs and no more (`test_purge_role_grants.py`).

### 2. Scrub-in-place vs hard-delete, per store, from a verified column inventory
- **`users`, `visits` → SCRUB PII columns in place**, keep the anonymized skeleton. Both anchor the append-only audit trail (and `users` has inbound FKs); a hard delete would orphan the evidence DPDP itself depends on. NOT-NULL columns get redacted markers; `users.external_idp_subject` (unique per tenant) gets a per-row-unique `purged-<id>` marker. `purged_at` stamps a scrubbed row so a re-run is idempotent (DA-S1) and crash-resumable.
- **`outbox_messages`, `portal_contact_verifications` → DELETE** (transient; naturally idempotent).
- The scrub set is derived from a **verified column inventory**, not a hand list — this is what caught `visits.purpose` (visitor free text) being missed (SP-B3 / rejected alternative). All six visit PII columns are scrubbed (`visitor_full_name`, `contact_value`, `host_hint`, `purpose`, `denial_reason`, `checkin_code_hash`).

### 3. Each store's reference timestamp is chosen explicitly — never `updated_at` (DA-B1)
`updated_at` moves on the scrub itself, so it cannot be the retention clock. Each category names its own reference:
- `users` — `disabled_at` (retention runs *post-disable*; `disabled_at` is newly stamped when US-10's disable path runs).
- `visits` — terminal `Denied` by `decided_at`; abandoned non-terminal (`Requested`/`Registered`) by `created_at` (incl. orphaned NULL-host visits, SP-B3a).
- `outbox_messages`, `portal_contact_verifications` — `created_at`.
- On-site/mustering `CheckedIn`/`Safe` visits are **deliberately excluded** from the time-based purge (DA-B2): a person still on site or being accounted for in an evacuation is not "expired data."

Outbox is purged by age **across all statuses including `dispatched`** — the inverted "only `pending`/`failed`" predicate that would leave every dispatched row's encrypted PII+credential forever is rejected (SP-B3).

**Forward requirement — widen the abandoned-visit predicate as the lifecycle grows.** The purge currently ages out only `Requested`/`Registered` abandoned visits (the states reachable today) plus terminal `Denied`. The lifecycle also defines `Held`, `Awaiting Approval`, `Awaiting Dual Sign-off`, and terminal `Checked-out` — all of which hold visitor PII and none of which have a purge predicate yet. This is correct *today* only because those transitions are not yet built; when a story ships any of them (an approval flow, dual sign-off, or a checkout that stamps a completion timestamp), that story MUST add the state to the purge's age-out predicate (with its own reference timestamp — e.g. checkout completion for `Checked-out`), or its visitor PII will silently accumulate past retention. Whoever builds those transitions owns widening `_ABANDONED_STATUSES` / the visits predicate here; a verify-story reviewer on such a story should treat a missing purge predicate as a retention gap.

### 4. Right-to-erasure cascades over the FULL subject footprint, including BOTH outbox anchors (DA-B3)
A visitor's `contact_value` lives on `visits` **and** `portal_contact_verifications`, and their `outbox_messages` anchor to **both** visit ids (`aggregate_type='visit'`) **and** verification ids (`aggregate_type='portal_contact_verification'`, per ADR-004 §4). Erasure collects both anchor id sets *before* scrubbing (the scrub blanks the contact it would otherwise match on), then deletes every anchored outbox row, deletes the verification rows, and scrubs the visit rows. Missing the verification-id anchor would strand a subject's OTP-dispatch rows — the specific gap DA-B3 flagged. A staff subject is erased by scrubbing the `users` row.

### 5. On-site erasure is REFUSED, not silently partial (DA-B2)
Erasure of a subject with a `CheckedIn` or `Safe` visit raises `OnSiteErasureRefused` and mutates nothing — you cannot anonymize someone you must still account for in an evacuation. The operator completes checkout first, then erases. This is a compliance-owner-confirmable life-safety carve-out, surfaced (Constraint 1), not decided unilaterally.

### 6. The erasure audit's `subject_ref` is a KEYED HMAC — never a reversible contact (SP-B1)
`audit_events` is append-only and **purge/erasure-exempt** (it is the evidence trail), so anything written there is permanently un-erasable. A bare `sha256(contact)` is reversible for a low-entropy contact (a phone/email keyspace) — writing one into the forever-store would defeat the erasure it records. The erasure audit therefore stores a **keyed HMAC** of the identifier (`app/crypto/hmac_hash.py`, the same keyed-hash discipline ADR-004 applied to the OTP) plus counts — enough to prove an erasure happened for *this* subject without retaining a recoverable contact. The time-based purge writes one PII-free `retention.purge` audit per tenant (counts + cutoffs, no subject data).

### 7. Human-gated activation, dry-run by default (Constraint 2)
The purge/erasure run via ops scripts (`scripts/purge_expired.py`, `scripts/erase_subject.py`), **never autonomously** — sensitive irreversible ops never loop or run on merge (AGENTS.md). `--execute` is fenced behind the full guard set, so no single misconfiguration triggers a real run:
1. `--execute` is explicit (dry-run is the default and mutates nothing / writes no audit);
2. `--confirm-tenant <slug>` must echo the exact target slug;
3. `settings.retention_purge_enabled` must be True (the compliance-owner flip, default OFF);
4. `settings.app_environment` must not be `production`.

### 8. Retention windows are config placeholders, not policy (Constraint 1)
`resolve_retention(tenant, category)` returns the tenant's `retention_policies` override or a config default. The defaults (users 180d post-disable, visits 90d, outbox 7d, contact-verifications 1d) are the prior stories' deferred values — **NOT ratified DPDP policy**. A per-tenant override row changes a window with no code change; ratifying the final windows is a tracked GA-gate compliance decision this story does not close.

## Consequences

**Benefits**
- Tenant isolation for an irreversible op is a database-enforced structural guarantee, not "we tested the queries we wrote."
- The anonymized skeleton preserves purpose-limitation and the audit evidence DPDP depends on, without orphaning FKs.
- Erasure is complete across the real subject footprint (both outbox anchors), and its own audit record cannot re-identify the erased subject.
- Every compliance decision the mechanism cannot ratify is a config/parameter/policy change and is surfaced for sign-off, not baked into code.

**Costs / risks**
- A third DB role (`vms_purge`) and a dedicated session helper to maintain alongside `vms_app`/`vms_migrator`.
- Scrub-in-place means a "purged" row still exists (anonymized); whether the scrubbed skeleton + retained `tracking_reference` + keyed-HMAC audit constitute a re-identification path under DPDP is an open compliance question (see below).
- The retention clock is per-store and explicit — adding a new PII store means explicitly choosing its reference timestamp and scrub/delete disposition, not inheriting a default.

**Open (human/compliance) questions — the DPDP GA gate this story does NOT close**
- The final retention windows per category.
- Whether Indian DPDP treats anonymization-in-place as satisfying erasure, per category.
- The exact life-safety carve-out for erasing an on-site visitor.
- Whether the scrubbed skeleton + retained `tracking_reference`/audit trail + keyed-HMAC `subject_ref` together constitute a re-identification path.

## References
- Story: US-07 (`docs/plans/US-07.md`)
- Design-gate review: `docs/reviews/US-07-review.md` (DA-B1..B3, SP-B1..B3)
- Related: ADR-001 (roles/RLS), ADR-002 (outbox), ADR-004 (portal OTP / verification anchors, keyed HMAC)
