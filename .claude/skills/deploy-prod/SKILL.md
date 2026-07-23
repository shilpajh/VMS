---
name: deploy-prod
description: Manual, human-controlled production deployment for Smart VMS, including the git steps for selecting the exact approved commit and tagging what was released. Never invoked automatically by any agent or loop.
argument-hint: "<release>"
disable-model-invocation: true
---

# Production deployment (human-invoked only)

Input: $ARGUMENTS

Preconditions (all must be evidenced before any action):
1. /release-readiness completed with human sign-off recorded, naming an exact approved commit SHA — not a branch name, which can move.
2. Change ticket approved; backup confirmed; rollback plan attached and rehearsed in non-prod.
3. A named human is present and explicitly confirms each step.

## Git steps (read side)
4. `git fetch origin --tags`.
5. `git checkout <approved-SHA>` (detached, exact commit from the sign-off record — never `main`, never a branch tip).
6. `git status --porcelain` empty, and confirm `git rev-parse HEAD` equals the SHA in the sign-off record, verbatim, before proceeding. Any mismatch → stop.

## Deploy steps
7. Apply via the protected pipeline with manual approval gate → verify health probes → run golden-path smoke → confirm audit events flowing.

## Git steps (write side — the only push this skill ever performs)
8. On successful deploy: create an **annotated, signed tag** at the deployed SHA, e.g. `release/2026.1`, and `git push origin release/2026.1` — a tag push only, never a push of code/commits to `main` or any branch.
9. Commit the deployment evidence (ref/SHA, time, smoke + audit results, rollback readiness) to `docs/deploys/` on a short-lived evidence branch and open a PR — never a direct push to a protected branch.

If any step fails: stop, execute the rollback plan (which may include deleting/repointing the tag if it was pushed prematurely), notify incident contacts. No retries without human instruction. No agent may push code to `main` or any release branch under any circumstance — the tag push in step 8 is the sole exception, and only after a successful deploy.
