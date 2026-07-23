---
paths:
  - "tests/**"
  - "**/*_test.py"
  - "**/*.test.ts"
  - "**/*.test.tsx"
  - "**/*_test.dart"
---

# Test rules
- Encode PRD numbers as assertions (< 1 s QR lookup, < 2 s kiosk response, 1.5 s face verify, 10 s notification, 500 concurrent check-ins) — report actual measurements.
- Mandatory suites per feature: state-machine transitions (valid + invalid), tenant-isolation attempts, command idempotency (duplicate delivery), outage/replay reconciliation, audit-event presence.
- Device simulators (printer, QR scanner, biometric result, access panel) for E2E; real panels only in designated non-prod environments.
- Synthetic data only. A criterion that can't be tested yet is reported NOT TESTABLE, never skipped silently.
