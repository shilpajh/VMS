---
name: release-readiness
description: Produce Smart VMS release evidence, migration/rollback plan, open-risk register and sign-off checklist via delivery-orchestrator.
argument-hint: "<release>"
disable-model-invocation: true
---

# Release readiness workflow

Input: $ARGUMENTS

1. delivery-orchestrator reads the PRD traceability matrix; confirms acceptance evidence per in-scope story.
2. Migration/rollback review — rollback must have been exercised in non-prod.
3. Final security/privacy review sign-off; zero unresolved blockers.
4. Performance + outage/resilience results vs. PRD thresholds, with actual numbers.
5. Produce change log, migration/rollback plan, unresolved-risk register, customer sign-off pack.
6. Human approval recorded. Loop budget: 2 iterations; gaps become listed risks, never silently waived.

Production deployment remains a separate, human-invoked /deploy-prod.
