---
name: graph-query
description: Use the project's graphify knowledge graph to answer "how does X connect to Y" / "what touches this table" / "what's the blast radius of this change" questions, instead of grepping or reading files one at a time. Query first, read files only for what the graph can't tell you (exact line-level logic).
argument-hint: "<question>"
disable-model-invocation: false
---

# Query the knowledge graph before reading files

Input: $ARGUMENTS

Graphify has mapped this repo (Python core, React web, Flutter kiosk, C# edge connector, Postgres schema, Terraform, and the spec/doc artifacts under specs/ and packages/contracts/) into `graphify-out/graph.json`. It is local, deterministic for code (tree-sitter, no LLM), and every edge is tagged EXTRACTED (explicit) or INFERRED (resolved) — never treat an INFERRED edge as ground truth without a quick confirmation read of the cited file/line.

## When to reach for this instead of Read/Grep
- "What touches the visit-lifecycle state machine / the credential table / the biometric template store?" → `graphify query "..."` or `graphify explain "<Node>"`
- "How does the kiosk's check-in flow reach the Python backend?" → `graphify path "KioskCheckIn" "VisitService"`
- "If I change this contract, what breaks?" (blast radius before a risky edit) → `graphify explain "<contract-node>"`, read its full connection list
- "Which two tickets are safe to dispatch in parallel?" (delivery-orchestrator, before /execute-story concurrency) → `graphify prs --conflicts` if PRs already exist, or `graphify path` between the two file-map targets to check for a shared community
- Any GATHER step in /execute-story where the plan references a component you haven't already read this session

## When to still read the file directly
- The graph tells you WHAT connects to WHAT — it does not replace reading the actual logic once you've scoped down to the right file. Query first to scope, then read only what's relevant.
- Anything the graph marks AMBIGUOUS needs a direct read to resolve, not another query.

## Keeping the graph current
`graphify hook install` (one-time, per clone) auto-rebuilds after each commit — AST only, no API cost, and it sets up a merge driver so `graph.json` never carries conflict markers even with two people committing in parallel. If you suspect staleness anyway, run `/graphify . --update` before relying on a query result for a security or architecture decision.

## Compliance note
Never point graphify's semantic (doc/PDF/image) extraction at real customer visitor data, biometric sample images, or secrets — see .graphifyignore. Code and Postgres schema extraction are local-only and fine to include; docs and images route through an LLM backend and should only ever contain synthetic or already-approved-for-sharing content (specs, ADRs, the PRD, Gherkin features).
