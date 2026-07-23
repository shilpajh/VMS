---
name: debug-systematically
description: Structured 4-phase root-cause diagnosis for a Smart VMS verifier or test that has failed twice in a row inside /execute-story, run ONCE before the loop escalates to a human. Diagnoses; does not patch over symptoms.
argument-hint: "<story-ID> <failing-verifier>"
disable-model-invocation: true
---

# Systematic debugging (last structured attempt before escalation)

Input: $ARGUMENTS

Triggered by /execute-story's no-progress rule on the FIRST occurrence only (two identical consecutive failures). If this pass doesn't resolve it, escalate to a human per the loop's stopping condition — do not run this twice in a row as a substitute for escalation.

## Phase 1 — Reproduce precisely
Isolate the smallest input that reproduces the failure. Record exact command, input, expected vs. actual. If it can't be reproduced deterministically, that fact IS the finding — report it, don't guess.

## Phase 2 — Root-cause trace
Trace backward from the failure to its actual origin, not its first visible symptom:
- **root-cause-tracing**: follow the data/control flow from the assertion failure back through each layer (API → domain → DB / edge command → ack) until you find where behavior first diverges from spec.
- **defense-in-depth check**: is this failure a sign that an earlier layer should have caught it and didn't (e.g., a tenant-scope check that should have rejected the request three layers up)? Note it even if patching the immediate layer would "fix" the test.
- **condition-based-waiting check**: if this is a timing/async failure (outbox delivery, command ack, kiosk reconnect), confirm the test waits on the actual condition (e.g., "command acked") rather than a fixed sleep — a flaky timing bug is not the same defect as a logic bug, and the fix is different.

## Phase 3 — Identify the actual fix
State the root cause in one sentence and name the specific file/layer that needs to change. If the fix would touch a different agent's owned area (e.g., a backend bug traced to an edge-connector contract mismatch), say so explicitly — don't silently patch outside your scope.

## Phase 4 — Verify before declaring fixed
Apply the fix, then confirm: the originally failing verifier now passes, the reproduction from Phase 1 no longer reproduces, and no other verifier regressed. Evidence, not a claim — attach the actual test output.

If Phase 1 or 2 doesn't converge on a clear root cause, stop here and escalate with everything gathered (this counts as the loop's escalation, not a failure of this skill).
