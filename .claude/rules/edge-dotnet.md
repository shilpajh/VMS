---
paths:
  - "apps/edge-connector/**/*.cs"
---

# Edge connector rules
- Outbound-only mTLS; the connector initiates all communication; no inbound listeners.
- Commands stored in an encrypted durable local queue.
- Every command requires tenant, site, device, correlation ID, expiry, and idempotency key; handlers safe under duplicate delivery.
- Credential expiry enforced locally/panel-side regardless of cloud reachability.
- Execute intent only: never invent approvals, clear Held, or transition visit status.
- Report command state (accepted/executed/failed/timed out) to the cloud.
- Never cache raw biometric data; never log PII or credentials; signed upgrades only.
