---
name: deploy-nonprod
description: Approved non-production deployment workflow for Smart VMS environments, including the git steps that select and record what gets deployed.
argument-hint: "<environment>"
disable-model-invocation: true
---

# Non-prod deployment

Input: $ARGUMENTS (sandbox | dev | staging only — refuse anything resembling production)

## Git steps (read side — always allowed)
1. `git fetch origin --tags` — sync refs before doing anything.
2. `git checkout <target-ref>` — the approved branch/PR ref for this deploy, never a local uncommitted state.
3. `git status --porcelain` must be empty and `git log -1` must match the ref that passed CI. If it doesn't match, stop — do not deploy an unverified tree.

## Deploy steps
4. Verify CI is green on the target ref (all merge gates).
5. Apply IaC to the named non-prod environment via the pipeline (builder owns).
6. Run post-deploy smoke: health probes, one golden-path E2E (invitation → QR check-in → host notification → badge command → check-out → audit).

## Git steps (write side — scoped, never to protected branches)
7. Record deployment evidence (ref/SHA, environment, time, smoke results) as a file under `docs/deploys/`.
8. Commit that evidence file and push to a **feature or evidence branch**, then open/update a PR — never `git push` directly to `main` or any release branch. If the environment is ephemeral (e.g., PR-preview), the evidence commit belongs on that PR's branch.

No production resources may be touched by this skill under any circumstances. No step in this skill may push to a protected branch or create/push a release tag — that is reserved for /deploy-prod.
