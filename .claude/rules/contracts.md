---
paths:
  - "packages/contracts/**"
---

# Contract rules
- OpenAPI for REST, AsyncAPI for events; generated typed clients for web/kiosk; contract tests gate merges.
- Contract changes require a contract ticket + owner approval from each consuming component (web, kiosk, core, edge).
- Adding or tightening a REQUIRED request field (or renaming a field / narrowing an enum) on a shared DTO is a breaking change for every consumer: either update each consumer in the same story, or explicitly create a follow-up ticket — never ship the backend change alone. Consumer unit tests that mock the HTTP layer do NOT catch this drift (they assert their own hand-written shape); the durable guard is a contract test validating each consumer's request model against the OpenAPI schema. US-13a made three portal fields required and shipped without the frontend; the drift surfaced only as production-path 422s, caught a whole story later (US-13b).
- Commands carry tenant, site, device, correlation ID, expiry, idempotency key. Error model is shared and typed.
- Vendor-specific shapes never appear in contracts — normalized outcomes only.
