# Smart VMS — Agent Operating System (SIMPLE)

A repo-local agent OS for executing the Smart VMS from the PRD (v2.2) and the Technology Stack & Implementation Scope doc, using Claude Code (portable to Codex — AGENTS.md is the tool-neutral contract).

**This is the SIMPLE variant** — 5 agents (same as LITE) and a **4-phase workflow (Plan / Execution / Testing / Documentation)** with **2 human gates**, collapsed from an earlier 9-step/3-gate version that turned out to be more ceremony than most stories' actual risk warranted. Every real safety property survives the collapse — verifier-first, tenant isolation, no automated denial, human review before merge — it's just not spread across nine separate skill invocations anymore.

## What's here

```
AGENTS.md                    Tool-neutral project contract (~always loaded)
CLAUDE.md                    Imports AGENTS.md + Claude-specific rules
.claude/
  agents/                    5 role subagents (orchestrator, architect, builder, reviewer, tester)
  rules/                     9 path-scoped rule files (load per directory) — unchanged, still the real safety net
  skills/                    12 skills: 4 per-story phase skills + 8 situational ones (POC, deploy, debug, release, bootstrap, schema-check, graph-query)
packages/contracts/
  statemachine/              visit-lifecycle.yaml — the 9-state machine as data
  openapi/  asyncapi/        REST + command/event specs (source of truth)
specs/
  features/                  Gherkin acceptance specs (US-11, US-12 as templates)
  traceability.md            PRD ID → specs → verifiers → owners
docs/architecture/adr/       ADR template
docs/memory/PROJECT_MEMORY.md  append-only log, one entry per finished story (written by /document-story)
```

## Why this is simpler, concretely

| | Old (9-step) | SIMPLE (4-phase) |
|---|---|---|
| Skills invoked per story | brainstorm-spec, spec-feature, plan-feature, write-verifiers, implement-story, confirm-schema, security-review, test-feature, finish-branch (9) | plan-story, execute-story, verify-story, document-story (4) |
| Human gates | 3 (spec, plan, full-diff) | 2 (plan, merge decision) |
| Documents produced per story | Separate spec + plan + verifier-state files | One plan document (docs/plans/<story-ID>.md) covering intent + contracts + plan |
| Schema/biometric gates | Separate skill invocations you had to remember to call | Checked inline as part of Execution's relevant task |

**The honest trade-off:** merging spec review and plan review into one pass means scope-creep and half-finished-work get caught in the same reading instead of two independent ones. For a small team moving at real velocity, this is worth it. If a story's risk genuinely warrants the extra separation (a Phase 2/3 story touching biometrics, access control, or a new tenancy pattern), nothing stops you from doing two review passes over the one document manually — the document structure (Part A/B/C) is designed to make that easy even though the *tooling* only enforces one gate.

## The 4-phase flow, per story

```
/plan-story US-xx        ONE document: intent + contracts (state-machine/API deltas,
                          ADR if triggered, a few Gherkin scenarios) + plan (definition
                          of done, file map, user journey, numbered tasks)
                            ── HUMAN GATE 1: plan approval ──
/execute-story US-xx     bounded build loop; tests written alongside each task;
                          /confirm-schema's checklist runs INLINE for any migration task;
                          /biometric-provider-poc still gates any new vendor SDK
/verify-story US-xx      ONE combined pass: compliance/security review + broader tests
                          (E2E, load, accessibility, resilience) in a single report
/document-story US-xx    re-verify, guardrail checklist, memory entry written,
                            ── HUMAN GATE 2: merge / keep / discard ──
```

**Quick Flow, unchanged:** ≤3 files, no state-machine/tenancy/biometric/credential/consent/contract impact → skip all of the above, implement directly under the path-scoped rules.

## Situational skills (invoked when relevant, not part of every story)

| Skill | When |
|---|---|
| `/bootstrap-environment` | Day 0, once |
| `/confirm-schema` | Called inline by /execute-story for any migration task; can also be run standalone |
| `/biometric-provider-poc` | Before any biometric vendor/device is adopted |
| `/debug-systematically` | Runs once automatically when /execute-story's no-progress rule trips |
| `/graph-query` | Any time you need to scope down across the multi-language monorepo before reading files |
| `/release-readiness` | Once per release, not per story |
| `/deploy-nonprod`, `/deploy-prod` | Deployment only; `/deploy-prod` is human-invoked only |

## The 5 agents

| Agent | Authority | Must not do |
|---|---|---|
| delivery-orchestrator | Plans, slices, sequences, runs loops, persists review reports, release-readiness evidence | Implement broad changes directly |
| domain-architect | Visit lifecycle, tenant boundaries, modules, ADRs, event schemas | Choose vendor SDKs alone; write code |
| builder | Every implementation surface (Python/React/Flutter/C#/Azure/integrations), deferring to the path-scoped rule for wherever it's working | Approve its own work; skip a POC/schema gate |
| security-privacy-reviewer | Blocks unsafe changes (read-only) | Implement features |
| qa-automation-engineer | Tests, verifiers, broader suite | Relax acceptance criteria; fix app code |

## Compound Engineering (Kieran Klaassen / Every.to) — the philosophy behind Documentation
We didn't install Every's compound-engineering-plugin (26 generic agents, 23 commands) — it would duplicate and dilute the domain-specific system already built here, the same reasoning that kept us from installing Superpowers/Spec Kit/BMAD wholesale. What we adopted is the underlying **principle**: Plan → Work → Review → Compound, where skipping the fourth step is, in the source's own words, "traditional engineering with AI assistance," not compound engineering.

Your 4 phases already map to the first three (`/plan-story` = Plan, `/execute-story` = Work, `/verify-story` = Review). The gap was **Compound** — `/document-story` used to just *log* a gotcha in the memory entry. It now requires asking, for every gotcha: **would the system catch this automatically next time?** If not, the story proposes a specific rule/skill/agent-prompt change as its own clearly labeled diff for Gate 2's human to explicitly approve — never a silent edit to `.claude/rules/` or `.claude/agents/` bundled into the feature diff, which would otherwise conflict with AGENTS.md's self-protection guardrail.

Also adopted: the **three questions** (hardest decision / rejected alternatives / least confident part), now a mandatory closing section of every plan document — cheap, and gives Gate 1's human reviewer sharper signal than the plan's structure alone provides.

## RTK (rtk-ai/rtk) — command-output compression
Complements graphify but covers a different cost: graphify helps you avoid unnecessary file reads; RTK compresses the *output* of Bash-tool commands you do run — `git status/diff/log`, `pytest`/`cargo test`/`go test`, linters, `docker ps` — by 60-90%, transparently, via a PreToolUse hook. Installed once in Day 0 (`/bootstrap-environment`):
```
brew install rtk
rtk init -g          # installs the Claude Code hook; restart Claude Code after
```
No skill or agent instruction needs to change — the hook rewrites `git status` to its `rtk` equivalent before execution, automatically, for every agent invocation from then on. **Scope limits, stated plainly:** it only intercepts Bash tool calls — `Read`/`Grep`/`Glob` bypass it entirely (that's what `/graph-query` is for). It also doesn't yet have a native filter for `flutter test` or `dotnet test` — strongest coverage today is Python/JS/Go/Rust test runners and linters, which covers your backend and web frontend well but not yet the kiosk or edge-connector test output.

## Caveman (JuliusBrussee/caveman) — reply-token compression
A third, distinct token-cost lever alongside RTK and graphify: RTK compresses Bash command *output*; graphify avoids unnecessary file *reads*; caveman compresses the agent's own *replies* by ~65%, terse-not-lossy (only output/reply tokens — thinking/reasoning tokens are untouched). Installed in Day 0 alongside RTK:
```
curl -fsSL https://raw.githubusercontent.com/JuliusBrussee/caveman/main/install.sh | bash
```
**The boundary that matters most here (see AGENTS.md's "Communication style" section):**
- **Terse, always fine:** agent-to-agent status updates, loop iteration logs, commit messages (`/caveman-commit` — already produces Conventional Commits format, a direct fit for the git policy above), and the Should-fix/Notes tiers of a `/verify-story` report (`/caveman-review`'s one-line format).
- **Full prose, never compressed:** plan documents (Gate 1 content), Blocking findings in a review report, ADRs, Gherkin scenarios, PR descriptions for Gate 2. A compressed compliance finding is not an acceptable substitute for the full rule citation.
- **`/caveman-compress <file>`** is safe to try on `docs/memory/PROJECT_MEMORY.md` entries (already short and factual) — never on `AGENTS.md` or `.claude/rules/*.md` without a human diffing the compressed version line-by-line first, since compliance rules carry legally-meaningful qualifiers a lossy-feeling compression could blur.

## Git operations
Commits happen only on a story's own feature branch (`/execute-story` creates it), pushed to that branch/PR — never to `main`. `/deploy-prod` is the only place a tag gets pushed, after a successful deploy, human-invoked only.

## Graphify (codebase knowledge graph)
Same as before — `/graph-query` scopes down across the monorepo before reading files. See `.graphifyignore` for what's excluded from its semantic (LLM-backed) extraction pass.

## Install
Copy AGENTS.md, CLAUDE.md, .claude/, packages/, specs/, docs/ into your repo root. Run `/bootstrap-environment` once, then `/plan-story US-10` to create your first real database schema (tenants/users/roles) through the gated pipeline. Enforce hard controls (secret scanning, tenant-isolation tests, branch protection, manual prod approval) in CI — hooks and CI, not prompts, are the enforcement layer.

## Pre-flight checklist
Same blocking items as the full OS: repo skeleton scaffolded, CI actually enforcing the verification gate, branch protection configured, secrets in Key Vault not `.env`, spend caps configured at the account level, named humans assigned to both gates. A gate with no assigned owner gets rubber-stamped.
