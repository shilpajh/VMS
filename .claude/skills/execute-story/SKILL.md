---
name: execute-story
description: EXECUTION phase — build the story from its approved plan. Tests are written alongside each task, not as a separate ceremony with its own gate. Merges what used to be two separate steps (write failing verifiers, then implement) into one bounded build loop.
argument-hint: "<story-ID>"
disable-model-invocation: true
---

# Execute (build loop: gather → act → verify → repeat)

Input: $ARGUMENTS — must reference docs/plans/<story-ID>.md with Status: Approved. If missing, stop, run /plan-story first.

loop:
  name: execute
  objective: Make the plan's Definition of Done true, with tests proving it
  maximum_iterations: 3
  guardrails:
    max_files_changed: 25
    max_runtime_minutes: 25
    no_progress_rule: two consecutive iterations with no test-pass-count change → run /debug-systematically once, then escalate if still stuck

## Iteration 1 setup
- Confirm on the story's feature branch, from a clean baseline (`git fetch origin && git checkout -b feature/<story-ID> origin/main`; run the existing suite once, confirm green before touching anything).

## Per task (from the plan's numbered task list)
1. Write one failing test for that task's specific behavior first — this is not optional for anything touching domain logic, state transitions, or tenant scoping. Confirm it fails for the expected reason.
2. Write the minimal code to pass it, refactor, move on.
3. Independent tasks (no file overlap, no ordering dependency per the plan's file map) may run as concurrent `builder` instances rather than serially.
4. **If this task is a migration**: run through the `/confirm-schema` checklist inline, right here, as part of finishing the task — not as a separate skill invocation the user has to remember to call. Tenancy columns/indexes, state-machine alignment if visit-related, audit/retention registration, tested rollback, and (via `/graph-query`) confirm only the intended module writes to the new table. Unchecked items block this task, not just get noted.
5. **If this task adds a biometric/vendor SDK dependency**: confirm `/biometric-provider-poc` has already passed for that vendor/modality — don't add the dependency speculatively ahead of it.

## Standing invariants (checked every iteration, not just at the end)
- Tenant scoping on every query/endpoint touching visitor/visit/credential/audit data.
- No automated denial — any Held/Denied path from a biometric/watchlist signal requires a human-review step.
- Physical actions are idempotent async commands, never a direct synchronous hardware call.
- Every state transition and high-risk action writes an audit event (actor, timestamp, policy version, reason, correlation ID).
- Never log PII, credentials, raw documents, or biometric data.

## Commit and exit
Commit to the feature branch with a Conventional Commit message referencing the story ID after each task's tests pass. When every task in the plan is done and the Definition of Done is met: exit to /verify-story.

## Spec-contradiction rule
If a task reveals the plan itself was wrong, stop and ask — go back to /plan-story, get the correction approved, then resume. Never quietly work around it in code.

If the HUMAN directs a mid-execution change that contradicts the approved plan (e.g. "actually, make it look like X" reversing a Gate-1 decision), that's a legitimate human amendment — but record it in the plan doc as a clearly-labeled Gate-1 amendment *in the same commit or the next one*, before continuing. Changing only the code leaves the plan and the code disagreeing, which reads to the next reviewer as a silent scope violation (US-13b: a human-directed restyle reversed a Gate-1 decision and wasn't documented until /verify-story flagged the drift). A human-directed change still needs the plan updated, not just the code.
