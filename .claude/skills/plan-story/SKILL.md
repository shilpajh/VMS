---
name: plan-story
description: PLAN phase — the single step for turning a PRD story into an approved, implementable plan. Merges what used to be three separate steps (spec, contracts, plan) into one document and one human gate, for teams where three review cycles per story was more ceremony than the story's actual risk warranted.
argument-hint: "<story-ID>"
disable-model-invocation: true
---

# Plan (one document, one gate)

Input: $ARGUMENTS

## Quick Flow check first
Touches ≤3 files, no state-machine/tenancy/biometric/credential/consent/contract impact? Skip this whole skill — implement directly under the path-scoped rules. Most genuinely trivial changes (copy tweaks, a config value, a CSS fix) should never reach this skill at all.

## Otherwise, produce ONE document: docs/plans/<story-ID>.md

**Part A — Intent** (replaces the old separate spec step)
- Problem: what fails or is missing today, one paragraph, grounded in the actual PRD story and its acceptance criteria.
- Solution: what this change does, in behavior terms, not implementation.
- Out of scope: explicit — the scope-creep fence. State what this story deliberately does NOT cover.
- Risks: anything non-obvious about failure modes, edge cases, or what a careless implementation would get wrong.

**Part B — Contracts** (replaces the old separate spec-feature step; only write what actually changes)
- If this touches the visit lifecycle: the delta to packages/contracts/statemachine/visit-lifecycle.yaml (new/changed transitions, `requires_human` flags, audit events). Write an ADR in docs/architecture/adr/ if this changes a state, a tenancy schema, an event contract, security posture, a vendor, offline-authorization behavior, or residency/retention — per AGENTS.md's ADR triggers. Most stories touch nothing here — don't force this section if there's genuinely no contract change.
- If this touches an API: the OpenAPI/AsyncAPI delta (packages/contracts/), including 403/409 responses where relevant.
- If this needs a new permission: grep the existing `permissions`/`role_permissions` seed migrations first — a permission fitting this exact purpose may already be seeded (e.g. anticipating a later story) under a different name than the one that first comes to mind. Proposing a redundant new permission + RBAC migration when an existing one already covers it is scope the plan doesn't need (US-01 caught this mid-`/execute-story`, not here, where it belongs).
- 2-4 Gherkin scenarios covering the happy path plus the sharpest edge case (cross-tenant isolation, an invalid transition, or similar) — not exhaustive, just enough to anchor the acceptance criteria concretely. Full exhaustive scenario coverage happens in verify-story's tests, not here.

**Part C — Plan** (replaces the old separate plan-feature step)
- Definition of done: phrased so execute-story can turn it directly into tests.
- File map: every file touched, grouped by surface (backend/frontend/kiosk/edge/infra/contracts). >25 files → split the story.
- User journey: the demo path, step by step.
- Numbered tasks: file + change + test + note if it's a schema/biometric/vendor task requiring `/confirm-schema` or `/biometric-provider-poc` downstream.

## Three questions (add to the end of every plan, before the gate)
Answer these explicitly in the plan document — they surface exactly what a human reviewer needs and can't get from reading the plan's structure alone:
1. **What was the hardest decision in this plan?** Forces the tricky part into the open instead of hiding inside a bullet point.
2. **What alternatives were rejected, and why?** Shows the options considered — catches a bad default before it's built, not after.
3. **What's the least confident part of this plan?** The plan's author knows where the guesses are; asking makes them say so instead of letting a human find out the hard way mid-build.

## The one human gate
domain-architect (and security-privacy-reviewer, if the story touches tenancy/biometrics/consent) does a quick cold read for anything that looks like scope creep, a missed edge case, or a contract inconsistency — but the **human is the actual gate**: you read this one document (including its answers to the three questions above) and either approve it or send it back with what's wrong. One review cycle, not three. If something in here turns out wrong mid-build, execute-story stops and this document gets corrected — never silently worked around.

Exit: docs/plans/<story-ID>.md, Status: Approved → /execute-story.
