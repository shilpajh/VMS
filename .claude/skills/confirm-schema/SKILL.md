---
name: confirm-schema
description: Structured confirmation checklist for any new/changed database table or migration in the Smart VMS, run before /verify-story on any story whose file map includes an Alembic migration. Confirms the table architecture against the state machine, tenancy rules, and retention policy — not just "does it run."
argument-hint: "<story-ID> <migration-file>"
disable-model-invocation: true
---

# Confirm table architecture

Input: $ARGUMENTS

Run this on every migration before /verify-story, not just once at project start — every story that adds or changes schema goes through it.

## 1. Tenancy
- [ ] Every new table holding visitor, visit, credential, document, or audit data has a `tenant_id` column with an index (or is explicitly justified as tenant-global, e.g. a lookup/reference table — state this explicitly, don't leave it silent).
- [ ] Foreign keys stay within the same tenant boundary — a row never references another tenant's row.

## 2. State-machine alignment (for any visit-related table)
- [ ] The status/state column's allowed values match `packages/contracts/statemachine/visit-lifecycle.yaml` exactly — no invented states, no missing ones.
- [ ] Every transition marked `requires_human: true` in that spec has a corresponding actor/approver column captured somewhere in the schema (directly or via the audit table) — the schema must be able to prove a human decided, not just that a status changed.
- [ ] Terminal states (CheckedOut, Denied) have no schema path that allows a further transition (e.g., no foreign key or trigger that would let code silently move out of them).

## 3. Audit and compliance
- [ ] Audit-related tables are append-only: no UPDATE/DELETE grants, partitioned by time if high-volume.
- [ ] Every new table is registered with the retention/purge workflow (US-07) — state explicitly which policy applies and confirm the purge job covers it; a table nobody remembers to purge is a DPDP gap.
- [ ] Raw biometric data, if any column could hold it, is confirmed transient (deleted at the permitted point) — never a long-lived column.

## 4. Migration mechanics
- [ ] `downgrade()` is implemented and has actually been run once in a non-prod environment, not just present in the file.
- [ ] Destructive changes (drop column/table, narrowing a type) have a backfill/compatibility plan, not just the migration itself.
- [ ] Migration is idempotent against re-run in CI.
- [ ] Any `-1`-relative downgrade test pins the ABSOLUTE revision under test (`upgrade(cfg, "<this_revision>")` then `downgrade(-1)`), NEVER `upgrade(cfg, "head")` then `downgrade(-1)`. A `-1`-from-head test silently retargets the *newest* migration the moment a later one lands on top, so it stops exercising the migration it was written for and starts (usually failing on) the new one. This has recurred on 0002, 0003, and 0004 — pin the revision so the next migration doesn't break a prior story's test (US-13a gotcha).

## 5. Architecture-boundary check
- [ ] Run `/graph-query` on the new table — confirm it's written to only from its owning module's code (per the module boundaries: Tenant & Identity / Visitor & Visits / Approvals & Security / Credential Policy / Compliance / Integration / Audit & Reporting). A table written to from an unexpected module is a signal the module boundary has blurred — flag it to domain-architect even if this story doesn't need to fix it.

## Output
A pass/fail per checklist item, not a vague "looks fine." Any unchecked item is a Blocking finding fed into /verify-story, not a Note. If this is the FIRST migration establishing a new tenancy pattern (e.g., US-10's tenants/users/roles), confirm the ADR requirement was met before this checklist even starts — no ADR, no confirmation, back to /plan-story.
