# ADR-002: Transactional Outbox and the `visit.checkin_code.dispatch` Notification Contract

## Status
Proposed

## Context
US-11 ("Website pre-registration visibility") introduces the first asynchronous command boundary in Smart VMS. When a host approves a `Requested` visit, the visit transitions to `Registered`, a check-in code is issued, and that code must be delivered to the visitor's contact channel (email/SMS). AGENTS.md ("Non-negotiable rules") forbids calling any slow external vendor synchronously inside a request transaction, and `.claude/rules/backend-python.md` restates this: "No slow vendor calls in synchronous request transactions — offload via outbox/workers." The notification therefore cannot be sent inline in the approval request.

AGENTS.md already fixes the *runtime pattern* at the architecture level — "Azure-first: … Service Bus + transactional outbox." What is *not* yet decided, and what this ADR decides, is the concrete contract of that pattern's first instance:

- the `outbox_messages` table schema and its tenancy/RLS posture;
- the idempotency-key scheme that makes redelivery safe;
- the AsyncAPI message shape for `visit.checkin_code.dispatch`;
- the staleness/expiry send-gate the relay worker must honor;
- the at-rest protection for a payload that carries **both** a credential (the plaintext check-in code) **and** visitor PII (name/contact);
- the module ownership split between the Visitor & Visits domain (which *writes* the intent) and Integration (which *relays* it).

An ADR is mandatory here because this is an **event/command contract** decision (AGENTS.md ADR triggers) that will be consumed by the Python core and the workers now, and by the C# edge connector's durable command queue later. `.claude/rules/contracts.md` requires an AsyncAPI schema for events and owner approval from each consuming component; this ADR is the design-of-record those consumers reference.

Constraints that shape this decision:

- **Atomicity.** The `Requested → Registered` transition and the decision to notify must commit together, or not at all. A visit that is `Registered` in the database but whose notification was never enqueued (or the reverse) is a correctness defect. This is the classic dual-write problem the transactional-outbox pattern exists to solve: write the state change and the outbox row in **one** DB transaction; a separate relay reads committed outbox rows and publishes them.
- **At-least-once delivery ⇒ idempotency is mandatory.** Service Bus and any retrying relay deliver at-least-once. The message therefore carries an idempotency key so a redelivered message never double-sends a code. This is `.claude/rules/tests.md`'s mandatory "command idempotency (duplicate delivery)" suite.
- **The payload is sensitive.** Unlike the identity-domain rows in ADR-001, `outbox_messages.payload` holds a live credential (the plaintext check-in code — see ADR-001's precedent that credentials are never stored in the clear) plus visitor PII. RLS + disk encryption (the ADR-001 baseline) is not sufficient for a plaintext credential at rest.
- **Retention.** Undispatched/failed rows must not accumulate plaintext codes and PII indefinitely (US-11 review, Should-fix #5a). A max-age purge is required.
- **This message is a notification, not a panel command.** The full `tenant, site, device, correlation ID, expiry, idempotency key` command shape AGENTS.md ascribes to the C# edge connector applies to device/panel commands. A visitor notification has no `site`/`device`. This ADR defines a table general enough for both message families, with `site`/`device` nullable and not-applicable for notifications; the edge-connector command *variant* (with `site`/`device`/panel-side expiry) is a later ADR when that surface is built.

## Decision

### 1. Transactional outbox, single generic `outbox_messages` table
The Visitor & Visits domain, inside the same DB transaction that flips `Requested → Registered`, writes one `outbox_messages` row recording dispatch intent. The row commits atomically with the status change. A separate Integration relay worker reads committed `pending` rows, publishes to Azure Service Bus / the notification provider, marks the row `dispatched`, and the row is purged after successful dispatch (or after a max age if it fails — §5).

A single generic `outbox_messages` table is introduced now, with `visit.checkin_code.dispatch` as its first `message_type`. This is the modular-monolith default (AGENTS.md "Engineering philosophy" — YAGNI, one table, not a table per message type).

**Table `outbox_messages` (tenant-scoped, RLS per ADR-001's binding pattern):**

| Column | Type / constraint | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID NOT NULL, FK `tenants.id`, indexed, RLS (`ENABLE`+`FORCE`, `USING`+`WITH CHECK`, fail-closed single-arg `current_setting`) | Payload carries PII; tenant-scoped exactly like every ADR-001 tenant table. |
| `message_type` | `String(64)` NOT NULL | First value: `visit.checkin_code.dispatch`. |
| `aggregate_type` | `String(32)` NOT NULL | `visit`. |
| `aggregate_id` | UUID NOT NULL | The visit id. |
| `correlation_id` | UUID NOT NULL | = the visit's `correlation_id`; links submission → registered → dispatch. |
| `idempotency_key` | `String(128)` NOT NULL, **UNIQUE** | Deterministic — see §2. |
| `payload` | `BYTEA` NOT NULL (Key-Vault-envelope-encrypted ciphertext — see §5), **not** cleartext JSONB | Decrypted only in the relay worker's memory. Logical shape in §3. |
| `payload_key_ref` | `String(255)` NOT NULL | Key Vault key/version reference used to envelope-encrypt this row (enables rotation). |
| `status` | `String(16)` NOT NULL, CHECK in (`pending`,`dispatched`,`failed`) | |
| `attempts` | `Integer` NOT NULL, default 0 | |
| `next_attempt_at` | `timestamptz` NULLABLE | Backoff schedule. |
| `not_valid_after` | `timestamptz` NULLABLE | Copy of the code's `code_expires_at`; the send-gate (§4) reads this without decrypting the payload. |
| `site_id` | UUID NULLABLE | **Not applicable** to notifications; reserved for the later edge-connector command variant. |
| `device_id` | UUID NULLABLE | Same. |
| `created_at` | `timestamptz` NOT NULL, server default `now()` | Drives the 7-day max-age purge. |
| `dispatched_at` | `timestamptz` NULLABLE | |

`vms_app` (the RLS-subject request-path role) is granted `SELECT, INSERT, UPDATE` on `outbox_messages` — INSERT to record intent in the request transaction, and (see §6) the relay worker runs as a **separate** role, not `vms_app`. No `DELETE` grant to `vms_app`; purge runs under the `vms_migrator`/ops role (ADR-001 §4 precedent). Ships with a tested Alembic `downgrade()` (US-11 review, Should-fix #9), added to the migration's `RLS_TABLES` list.

### 2. Idempotency-key scheme
`idempotency_key` is **deterministic**, derived from the aggregate and purpose, not random and not client-supplied: `sha256("visit.checkin_code.dispatch:" || visit_id)` (hex). Because a visit can be approved exactly once (`Requested → Registered` is guarded and single-shot per ADR/US-11 §3), one dispatch message exists per visit; the UNIQUE constraint makes a duplicate INSERT (e.g. a retried approval that somehow re-ran) a no-op-or-conflict rather than a second notification. The relay worker and the downstream provider dedup on this key so a redelivered Service Bus message sends the code **once** (`.claude/rules/tests.md` idempotency suite). This is the outbox/command idempotency key and is distinct from the public-submission `Idempotency-Key` (US-11 §4 / review Should-fix #1), which is a separate, tenant-scoped, content-hashed dedup concern owned by the portal endpoint.

### 3. AsyncAPI message: `visit.checkin_code.dispatch`
Logical payload (the cleartext that is envelope-encrypted at rest per §5 and carried on the Service Bus message):

```yaml
# AsyncAPI 3.0 (excerpt) — channel: visit.checkin_code.dispatch
message:
  name: VisitCheckinCodeDispatch
  contentType: application/json
  payload:
    type: object
    required: [schema_version, tenant_id, visit_id, correlation_id,
               idempotency_key, contact_channel, contact_value,
               checkin_code, tracking_reference]
    properties:
      schema_version:    { type: string, const: "1" }
      tenant_id:         { type: string, format: uuid }
      visit_id:          { type: string, format: uuid }
      correlation_id:    { type: string, format: uuid }
      idempotency_key:   { type: string }          # = §2
      contact_channel:   { type: string, enum: [email, sms] }
      contact_value:     { type: string }           # PII
      checkin_code:      { type: string }           # credential, plaintext, transient
      tracking_reference:{ type: string, pattern: "^REQ-\\d+$" }
      code_expires_at:   { type: [string, "null"], format: date-time }
      tenant_display_name: { type: string }
```

`schema_version` is mandatory and pinned to `"1"`; any future breaking change bumps it and is a new contract ticket with sign-off from every consumer (`.claude/rules/contracts.md`). `site`/`device`/`expiry` device-command fields are deliberately absent from this notification message; they belong to the later edge-connector command family.

### 4. Staleness / expiry send-gate (US-11 review, Should-fix #10)
Before dispatching, the relay worker MUST re-read the source `visits` row and refuse to send if any of the following hold, marking the message `failed` (not `dispatched`) and emitting no notification:
- `not_valid_after` (the copied `code_expires_at`) is non-null and in the past;
- the visit's current `status` is no longer `Registered` (e.g. it was subsequently revoked/denied/checked-in by another path — the code is superseded);
- the visit's `checkin_code_hash` no longer matches the code implied by this message (a reissued code supersedes an older queued one).
This prevents delivering a stale or superseded credential. The gate is a re-read at dispatch time, not a trust of the enqueued snapshot.

### 5. At-rest protection of the payload (US-11 review, Should-fix #5)
`payload` is **application-level envelope-encrypted** with a Key-Vault-managed key (`payload_key_ref` records the key/version for rotation), stored as `BYTEA` ciphertext — not cleartext JSONB. Rationale: the payload holds a live credential plus PII; RLS + Azure disk encryption (the ADR-001 baseline for identity rows) is insufficient for a plaintext credential at rest. The plaintext exists only transiently: generated in the request (handed to the encrypt step), and decrypted only in the relay worker's memory at dispatch. Adjacent required rules:
- **Max-age purge:** `pending`/`failed` rows older than **7 days** are purged (run under the ops/`vms_migrator` role), so plaintext codes + PII never linger. This is a **placeholder pending real DPDP compliance sign-off** (mirroring ADR-001's retention caveat — not final policy) and is registered with the US-07 retention/purge workflow as a GA gate (US-11 review, Should-fix #3/#5a).
- **Never-log-payload rule:** the relay worker MUST NOT log the decrypted payload — not on success, not on retry, not on error. Errors log `id`, `tenant_id`, `message_type`, `idempotency_key`, `attempts` only. This is enforced by review and by a test asserting no `contact_value`/`checkin_code` appears in worker logs.

### 6. Module ownership split (Visitor & Visits writes, Integration relays)
- **Visitor & Visits** owns the *write* of the `outbox_messages` row: it happens inside the visit-approval transaction, in the domain layer, as the recorded intent of the `Registered` transition. This is the intended shared-boundary write, pre-declared so `/graph-query` community detection does not misread the `visits → outbox_messages` edge as a module blur (same treatment ADR-001 gave the `audit_events` shared sink).
- **Integration** owns the *relay worker* (`services/workers/`) and the notification provider adapter. The worker publishes to Service Bus, applies the §4 send-gate, and marks rows dispatched.
- **The relay worker MUST NOT run as the request-path `vms_app` role** (US-11 review, Notes). It runs under its own dedicated DB role with the narrow grants it needs (`SELECT`/`UPDATE` on `outbox_messages` under an appropriate tenant-context strategy, decrypt via its own Key Vault access). The worker's tenant-context strategy (how it sets `app.current_tenant_id` for a background, non-request read across tenants) is **not built in US-11** and gets its own security review when the worker is implemented — flagged, not resolved here.

## Consequences

**Benefits**
- The state change and its notification intent commit atomically — no dual-write correctness gap.
- Idempotency is contract-level, not best-effort: a deterministic key + UNIQUE constraint + provider dedup make double-send structurally hard.
- One generic outbox table fits the modular-monolith default and gives the later edge-connector command family a home without a second mechanism.
- The credential/PII payload gets protection proportional to its sensitivity (envelope encryption), and a bounded lifetime (7-day purge).
- A single AsyncAPI contract of record, versioned, that the workers consume now and the C# edge connector references later.

**Limitations / deliberately out of scope for the first cut**
- **The relay worker itself is not built in US-11.** US-11 builds only the *write* side (the domain writes the row). The worker, its tenant-context strategy, its Service Bus wiring, and the concrete notification vendor are later work with their own review.
- **Notification vendor is unchosen.** Not a biometric/OCR/CCTV/access-control vendor, so no POC/vendor-ADR gate applies (CLAUDE.md); the adapter is replaceable and the domain sees only the normalized command.
- **Ordering/priority across message types** is not modelled (single FIFO-enough relay for the first cut).
- **The edge-connector device-command variant** (with `site`/`device`/panel-side expiry) is a later ADR; `site_id`/`device_id` are reserved-nullable here.

**Operational impact**
- New Alembic migration for `outbox_messages` (may co-ship with `0002_visits`), with tested `downgrade()`, RLS enablement, and grants.
- A Key Vault key for payload envelope encryption + a rotation story; `payload_key_ref` supports rotation.
- A purge job (ops/`vms_migrator` role) enforcing the 7-day max age, registered with US-07.
- A dedicated worker DB role, separate from `vms_app`.

## Security and privacy impact
- **Tenant isolation:** `outbox_messages` is tenant-scoped with FORCE RLS (`USING`+`WITH CHECK`, fail-closed single-arg GUC) exactly per ADR-001. Cross-tenant read/write is a Blocking defect (`.claude/rules/security-privacy.md`).
- **Credential at rest:** the plaintext check-in code lives in the payload only as envelope-encrypted ciphertext (`BYTEA`), decrypted only transiently in the worker's memory. Never stored as cleartext JSONB.
- **PII:** `contact_value` and visitor name are PII — never logged (the never-log-payload rule, §5), envelope-encrypted at rest, and purged within 7 days (undispatched/failed) or on successful dispatch. This retention window is a **placeholder pending real DPDP compliance sign-off**, not final policy; the caveat must not be dropped.
- **Staleness:** the §4 send-gate prevents delivering an expired or superseded credential.
- **Least privilege:** the relay worker runs under its own role, never `vms_app`; the request path can INSERT but not DELETE; purge runs under the ops role.
- **Secrets:** the envelope-encryption key and the notification provider's credentials live in Key Vault / managed identity only — never in code, fixtures, prompts, or logs (AGENTS.md).
- **Audit:** the `Registered` transition that produces the outbox row emits `visit.registered` (US-11 §8) with the same `correlation_id` the outbox row carries, so the dispatch is traceable to its originating decision without the audit trail itself holding the code or contact value.

### Open questions surfaced to the orchestrator/human (not silently resolved)
- **O1 — Retention windows are placeholders.** The 7-day undispatched/failed purge (and US-11's 90-day terminal-state visitor-PII purge) are working placeholders to unblock the schema; both require real DPDP compliance sign-off before GA (US-11 review Should-fix #3/#5a/#8). Registered as GA gates, not resolved here.
- **O2 — Relay worker tenant-context strategy.** How a background worker safely sets `app.current_tenant_id` to read committed rows across tenants (without becoming a cross-tenant read path) is deferred to when the worker is built, with its own security review. Confirm the Integration owner accepts this split.
- **O3 — Envelope-encryption mechanism specifics.** Envelope encryption with a Key-Vault-managed key is decided; the exact primitive (e.g. AES-GCM data key wrapped by a Key Vault key) and rotation cadence are an execution/security-review detail to confirm, not an application-logic choice.
