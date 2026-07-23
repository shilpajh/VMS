---
paths:
  - "packages/contracts/**"
---

# Contract rules
- OpenAPI for REST, AsyncAPI for events; generated typed clients for web/kiosk; contract tests gate merges.
- Contract changes require a contract ticket + owner approval from each consuming component (web, kiosk, core, edge).
- Commands carry tenant, site, device, correlation ID, expiry, idempotency key. Error model is shared and typed.
- Vendor-specific shapes never appear in contracts — normalized outcomes only.
