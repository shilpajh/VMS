OpenAPI specs live here — one file per module (visits.yaml, approvals.yaml,
credentials.yaml...). FastAPI routes, TS/Dart clients, and contract tests are
generated/validated from these files. /plan-story owns changes; the design
gate reviews the diff. 403 (tenant scope) and 409 (invalid transition) response
declarations are mandatory on every endpoint touching visit data.
