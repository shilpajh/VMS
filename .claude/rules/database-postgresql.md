---
paths:
  - "services/**/migrations/**"
  - "services/**/models/**"
---

# PostgreSQL rules
- Every table holding tenant data carries tenant_id with an index; row-level security posture per the tenancy ADR.
- Alembic migrations must include a tested rollback; destructive changes need a backfill + safety plan.
- Audit/event tables are append-only; partition by time at scale; never UPDATE/DELETE audit rows.
- Retention/purge jobs must cover every new store added; deletion produces audit evidence.
