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
- A guard that gates a transition on a time window/expiry must be folded into the SAME guarded `UPDATE`'s `WHERE` clause as the tenant/status checks — never checked as a separate step after the row changes. A separate post-check creates a timing/behavior oracle: an expired-but-real input does observably more work (a row flipped then rolled back) than an entirely unknown one (zero rows matched) (US-01).
- When adding a literal-path route under an existing path-parameterized prefix of the same segment count (e.g. `POST /visits/checkin` alongside `GET /visits/{visit_id}`), register the literal route first. FastAPI/Starlette can otherwise resolve a method mismatch against the parameterized route to a 405, rather than falling through to the literal route that actually handles the request (US-01).
