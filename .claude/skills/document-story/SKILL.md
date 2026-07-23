---
name: document-story
description: DOCUMENTATION phase — the close-out. Guardrail checklist, memory entry, and the final human decision (merge/keep/discard), all as one step. This is where the story's documentation trail gets tied together, not written separately.
argument-hint: "<story-ID>"
disable-model-invocation: true
---

# Document (close-out: guardrails, memory, merge decision)

Input: $ARGUMENTS — must reference a story that passed /verify-story with no blocking findings.

## 1. Re-verify
Run the test suite one more time on the current branch tip — confirm green right now, not "was green earlier."

## 2. Guardrail checklist (mandatory, every story, no exceptions)
- [ ] No secret/credential anywhere in the diff.
- [ ] No real customer/visitor PII or biometric sample in any fixture added.
- [ ] Every new/changed table's tenant scoping was confirmed during /execute-story's inline schema check.
- [ ] No transition into Denied without `requires_human: true`.
- [ ] Every Definition-of-Done item from the plan is accounted for — passing or explicitly NOT AUTOMATABLE with its manual-check substitute.
- [ ] Any new paid vendor call (OCR/biometric/WhatsApp/SMS) has a rate limit or cost cap.
- [ ] Any public-portal-facing change has rate limiting/abuse protection.

Any unchecked box blocks the merge decision below until resolved or explicitly accepted with a written reason.

## 3. Write the memory entry AND compound the system (this is the step that matters most)
Per compound engineering's core rule: a solved problem that isn't fed back into the system is a note, not a compound gain. "Skip this and you've done traditional engineering with AI assistance" — the loop only pays off long-term if this step actually changes something, not just logs something.

First, append to docs/memory/PROJECT_MEMORY.md as before:
```
## <story-ID> — <one-line title> (<date>)
Built: <1-2 sentences>
Key decisions: <ADR reference or non-obvious choice a future story needs>
Gotchas: <anything that cost time to discover>
Depends on / blocks: <what this unblocks or still depends on>
Files of note: <2-4 paths a future story would actually need>
```
Keep it to 6-10 lines — future stories' plan phase reads the last 5-10 entries instead of re-deriving context; a rambling entry defeats that.

Then, for every Gotcha logged, ask explicitly: **would the system catch this automatically next time, or would the next story hit the same thing?** If the honest answer is "it would hit it again," this step is not done yet — but per AGENTS.md's self-protection guardrail, no agent edits `.claude/rules/`, `.claude/agents/`, or `.claude/skills/` as a quiet side effect of closing out a feature story. Instead, **propose** the specific change as its own clearly labeled diff, called out separately in the PR description (e.g. "**Constitution change proposed:** `security-privacy.md` +1 line — reason: X"), so Gate 2's human reviewer sees and approves it as a distinct decision, not a change bundled invisibly into the feature diff:
- A missing invariant → propose one line for the relevant `.claude/rules/*.md` file.
- A schema mistake `/confirm-schema` should have caught but didn't → propose a strengthened checklist item for that skill.
- A recurring pattern across 2+ stories → propose a new line in the relevant agent's prompt (`builder.md`, `domain-architect.md`, etc.), not just a memory entry that depends on someone reading it.
- A category of mistake with no home in any existing rule/skill → flag it explicitly to the human at Gate 2 as "this needs a new rule/skill, not just a note" rather than silently filing it away.

If the human approves the proposed constitution change at Gate 2, it merges in the same PR — this keeps the compound benefit (no separate bureaucratic PR for a one-line fix) without ever letting a rule change slip through unapproved or unnoticed.

A memory entry with an unresolved Gotcha and no corresponding system change is an incomplete Documentation phase — call this out rather than closing the story anyway.

## 4. The human decision
Present three options — merge/PR, keep branch (deferred), or discard — and let the human choose. On PR: link the plan, the review report (docs/reviews/<story-ID>-review.md), the new memory entry, and any rule/skill change made in step 3, in the description. On merge: update specs/traceability.md to Done, delete the local feature branch.

Never pushes to main, never merges a PR itself — per the git operations policy in AGENTS.md, that's always a human action.
