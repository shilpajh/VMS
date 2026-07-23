---
paths:
  - "infra/**"
---

# Azure infrastructure rules
- Terraform/Bicep only; no portal-clicked resources.
- Managed identities everywhere; no keys/connection strings in code or app settings; secrets in Key Vault/Managed HSM.
- Zone-redundant services; health probes; retry + dead-letter on all queues.
- Default target is sandbox/non-prod; production apply requires the manual /deploy-prod workflow.
- Data residency is a per-tenant region parameter, not a hardcoded default: an Indian tenant's PostgreSQL, Blob Storage, and Redis must all provision in an India Azure region (per PRD Section 8); the Terraform/Bicep module takes region as a variable — never assume a single global region for all tenants.
- OpenTelemetry + Application Insights wiring is part of every new service definition.
