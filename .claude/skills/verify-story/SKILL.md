---
name: verify-story
description: TESTING phase — one pass covering both compliance/security review and the broader test suite. Merges what used to be two separate steps into one report.
argument-hint: "<story-ID>"
disable-model-invocation: true
---

# Verify (compliance + security + broader tests, one pass)

Input: $ARGUMENTS — must reference a story that has completed /execute-story with its tests passing.

## 1. Compliance & security check (security-privacy-reviewer, read-only)
Read the diff cold against docs/plans/<story-ID>.md first — does it match the approved plan's scope, or has something crept in beyond it? Then the standing checklist: tenant isolation (any unscoped query is Blocking), state machine enforced in the domain layer not just UI, no automated denial, biometric privacy (raw-capture deletion, template segregation, consent linkage, Aadhaar never stored raw), audit completeness, command idempotency/expiry, secrets/logging hygiene, authN/authZ, retention/erasure coverage. Use `/graph-query` first for the blast radius of any touched compliance surface.

Findings in three buckets, persisted to docs/reviews/<story-ID>-review.md (the reviewer has no Write tool by design; the orchestrator persists this). **Blocking** findings are always full prose — file/line, the exact rule violated, and why, per AGENTS.md's Communication style section; a human may need to act on these without other context. **Should-fix** and **Notes** may use `/caveman-review`'s terse one-line format (`L42: 🔴 bug: user null. Add guard.`) — these are lower-stakes and read by the implementing agent, not a compliance sign-off.

## 2. Broader test suite (qa-automation-engineer)
E2E against simulators (printer, QR scanner, biometric result, access panel), load/performance against PRD thresholds (report actual measured numbers, never rounded toward passing), accessibility (WCAG 2.1 AA) and localization completeness for any touched UI, the 72-hour erasure SLA if this story touches purge/retention, avatar-jailbreak resistance if this story touches the conversational kiosk avatar, and resilience (network-loss/reconnect behavior) if this story touches the edge connector or offline kiosk paths.

Report: Criterion → Test → Result → Evidence. NOT TESTABLE items (needs a real device POC) are listed explicitly, never silently skipped.

## Remediation loop
Blocking findings go back to /execute-story. Maximum 2 remediation cycles on this combined check; unresolved blockers escalate to a human.

Exit: zero blocking findings AND every mapped acceptance criterion passes or is explicitly dispositioned → /document-story.
