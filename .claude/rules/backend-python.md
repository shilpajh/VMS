---
paths:
  - "services/core-api/**/*.py"
  - "services/workers/**/*.py"
---

# Python backend rules
- Python 3.12+, typed Pydantic v2 models, explicit DTOs at every API boundary.
- Validate authorization and tenant scope before database access — no exceptions.
- Enforce visit state transitions in the domain layer + DB transaction; invalid transitions raise domain errors.
- No slow vendor calls in synchronous request transactions — offload via outbox/workers.
- Physical actions publish idempotent commands (Service Bus + outbox); never direct device calls.
- Every transition/high-risk action writes an audit event: actor, timestamp, policy version, reason, correlation ID.
- Alembic migration with rollback for every schema change; tenant column + index on every new table holding tenant data.
- Never log PII, credentials, raw documents, or biometric data.
