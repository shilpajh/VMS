# ADR-003: Credential-Grant Command Contract and the `checkin_verified` Side Effect

## Status
Proposed

## Context
US-01 ("Pre-registered check-in", hardware-free QR slice) wires the `Registered -> CheckedIn` transition `packages/contracts/statemachine/visit-lifecycle.yaml` already reserved (`checkin_verified` trigger). PRD Section 3.4 requires that a badge/credential be issued at check-in, scoped by zone and time window. AGENTS.md's "Non-negotiable rules" require this to be an **asynchronous idempotent command** — "cloud records intent, edge executes and acknowledges. Never call panels/printers synchronously from Python" — but no device/panel-command event contract exists anywhere in this system yet; every prior async write (ADR-002's `visit.checkin_code.dispatch`) is a *notification*, not a *command*.

This is the first command contract, and it is written before `apps/edge-connector` has any real implementation (it is still a README scaffold). That is a deliberate repeat of ADR-002's own precedent — the domain writes the intent now; the consumer is a later story. What this ADR decides, specifically:

- the credential-grant command's payload shape, and why it deliberately does **not** carry a `zone` field;
- why both new outbox message types introduced by US-01 (credential-grant command, host-arrival notification) are envelope-encrypted uniformly, with no plaintext special case;
- the `expiry` field's placeholder semantics, recorded as an open question rather than settled design;
- the four-consumer contract-approval requirement this ADR triggers, and the gap left by wiring the side effect on only one of `CheckedIn`'s four entry transitions.

An ADR is mandatory here per AGENTS.md's triggers: this changes an event contract (new command family) and amends `visit-lifecycle.yaml` itself (a state-machine contract change, `.claude/rules/contracts.md`: "Contract changes require a contract ticket + owner approval from each consuming component").

This ADR was drafted after two independent design-gate cold reads (domain-architect, security-privacy-reviewer) on the US-01 plan, both of which independently found the same Blocking defect in an earlier draft (see Decision §2) and raised the `zone`-placeholder, `expiry`-conflation, and side-effect-asymmetry concerns folded in below.

## Decision

### 1. Command envelope: no `zone` field
`.claude/rules/contracts.md` defines the device-command envelope as `tenant, site, device, correlation_id, expiry, idempotency_key`. This is the shape every future badge-print/door-release command will reuse verbatim, so nothing throwaway belongs in it. `site_id`/`device_id` are both `null` in this story — no `sites`/`zones` schema exists yet (PRD 3.10, multi-site administration, is not in this wave) — and stay in the envelope as the correct, if currently unpopulated, place to express targeting. There is **no `zone` field**: an earlier draft proposed a placeholder string (`"site-default"`), which the domain-architect review flagged as the worst place to put a throwaway value, since every future device command would inherit it by "reuse verbatim." Zone-scoping is deferred entirely to whatever story builds real multi-site administration.

### 2. Both new payloads are envelope-encrypted, uniformly — no plaintext special case
An earlier draft of this ADR proposed leaving the credential-grant payload unencrypted, reasoning that it carries no visitor PII (opaque IDs and a time window only). Both independent design-gate reviews (domain-architect, security-privacy-reviewer) found this unbuildable and non-compliant: `outbox_messages.payload_key_ref` is `NOT NULL` (no schema support for a plaintext row), and ADR-002 §5 established "payload is always ciphertext" as the table's invariant — an unencrypted row would either fail the constraint or require a plaintext/ciphertext discriminator column ADR-002 never defined. **Decision: both `visit.credential_grant.command` and `visit.arrival.notify` are envelope-encrypted uniformly**, exactly like `visit.checkin_code.dispatch`. Encrypting a no-PII payload costs nothing; it avoids a special case in a table whose whole point is a single at-rest-protection invariant.

### 3. `expiry` is a known-wrong placeholder — open question, not settled design
The credential-grant command's `expiry` field reuses `visits.checkin_code_expires_at` — the deadline for the visitor to *arrive and use the code* (7-day `CHECKIN_CODE_VALIDITY`). This is **not** the credential's actual intended validity window (how long the visitor should retain access once on site), and using it as such produces an arrival-time-dependent, not visit-duration-dependent, badge lifetime: a visitor checking in on day 6 of a 7-day code gets a ~1-day credential; one checking in on day 1 gets ~6 days. Because AGENTS.md requires panel-side expiry enforcement to hold without cloud connectivity, a future edge connector would faithfully enforce this arbitrary expiry. **This is flagged as an open question, not resolved here**: a real visit-duration/credential-validity policy field does not exist yet, and inventing one speculatively ahead of the story that needs it would be scope creep in the other direction. Whoever builds the edge-connector command execution story must revisit this field before treating it as correct.

### 4. Four-consumer contract approval, including the edge-connector's, despite the scaffold
This ADR amends `packages/contracts/statemachine/visit-lifecycle.yaml` (adding `side_effects: [credential_grant_command]` to the `checkin_verified` transition) and introduces a new AsyncAPI command contract. `.claude/rules/contracts.md` requires "a contract ticket + owner approval from each consuming component" for any contract change. The four consumers of `visit-lifecycle.yaml` are **web** (React portals reading visit status), **kiosk** (Flutter, not yet built for this hardware-free wave but a future consumer of check-in status), **core** (this story's own implementation), and **edge** (the C# connector that will eventually execute the credential-grant command). Edge-connector sign-off is required as a matter of process even though `apps/edge-connector` is currently just a README scaffold with no maintainer yet assigned — the contract ticket should name this explicitly rather than silently skip a consumer that happens to not exist yet.

### 5. `credential_grant_command` is wired on only one of `CheckedIn`'s four entry transitions
`visit-lifecycle.yaml` allows `CheckedIn` to be reached via four transitions: `checkin_verified` (this story), `approver_confirm` (walk-in, US-02), `both_approvals_received` (dual sign-off), and `security_release` (Held release). Only `checkin_verified` declares `credential_grant_command` as a `side_effects` entry after this story. Unlike the `credential_lifecycle` invariant, which forces `credential_deprovision_command` on *every* exit from `CheckedIn`, there is **no equivalent invariant** forcing a credential grant on every *entry*. This is a known, tracked gap (recorded as an inline comment in `visit-lifecycle.yaml` itself, next to the `checkin_verified` transition) rather than a silently-assumed completeness — a future walk-in/dual-signoff/hold-release story must either add the same side effect to its own transition or the gap persists.

## Consequences

**Benefits**
- Establishes the reusable device-command envelope shape once, correctly scoped (no throwaway fields), before any real edge-connector consumer exists to be broken by a later correction.
- Uniform encryption keeps `outbox_messages`' at-rest invariant simple — one rule, no exceptions, no discriminator column.
- The known-placeholder fields (`expiry`, absent `zone`) are named as open questions in the contract itself, not discovered later as silent bugs.

**Limitations / deliberately out of scope for this cut**
- No real credential-validity/visit-duration policy exists; `expiry` is wrong until that policy exists and this contract is revisited.
- No sites/zones schema exists; targeting is `null`/`null` until a multi-site administration story ships.
- `apps/edge-connector` has no real implementation; this command has no consumer yet (matches ADR-002's precedent for `visit.checkin_code.dispatch`).
- The credential-grant side effect is not yet invariant-enforced across all four `CheckedIn`-entry transitions.

**Operational impact**
- Two new AsyncAPI contract files (`credential-grant-command.yaml`, `visit-arrival-notify.yaml`); no new database table (reuses `outbox_messages`).
- `visit-lifecycle.yaml`'s `checkin_verified` transition gains a `side_effects` entry — a contract-file change requiring the four-consumer sign-off in Decision §4.

## Security and privacy impact
- **Tenant isolation:** both new message types write to the existing tenant-scoped, RLS-enforced `outbox_messages` table (ADR-001's pattern, unchanged).
- **No automated denial / watchlist:** unaffected by this ADR — `watchlist_clear`'s stub status and the unwired `Registered -> Held` edge are covered by the US-01 plan directly, not this contract.
- **PII:** the credential-grant payload carries none; the arrival-notify payload carries `host_email`/`visitor_full_name` and is envelope-encrypted, registered under the same retention/purge GA gate as `visit.checkin_code.dispatch` (US-01 plan, task 10).
- **Least privilege / secrets:** unchanged from ADR-002 — envelope-encryption keys in Key Vault only, never in code/fixtures/logs.
- **Panel-side expiry:** the known-wrong `expiry` placeholder (Decision §3) is a real, if currently theoretical, security posture concern — a future edge-connector story enforcing it panel-side must not treat it as correct without revisiting this ADR first.

### Open questions surfaced to the orchestrator/human (not silently resolved)
- **O1 — Credential validity/visit-duration policy.** `expiry` needs a real field once a visit-duration or credential-validity policy exists. Not resolved here.
- **O2 — Zone/site targeting.** `site_id`/`device_id` stay `null` until multi-site administration is built. Not resolved here.
- **O3 — Side-effect invariant gap.** No contract-level invariant yet forces a credential grant on every entry into `CheckedIn`. Flagged in `visit-lifecycle.yaml` itself; not enforced.
- **O4 — Edge-connector contract sign-off.** No maintainer is yet assigned to `apps/edge-connector`; the four-consumer contract-ticket process (Decision §4) should name this explicitly when the contract ticket is filed.
