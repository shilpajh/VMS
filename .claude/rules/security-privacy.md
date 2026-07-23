---
paths:
  - "services/**"
  - "apps/**"
  - "infra/**"
  - "packages/contracts/**"
---

# Security and privacy rules
- Never log PII, credentials, raw identity documents, biometric captures, or templates.
- Any biometric/watchlist uncertainty transitions to Held and needs authorized human review — no automated denial anywhere.
- Consent is explicit, versioned, purpose-limited, and linked before biometric capture. A recorded consent references the exact document version it was given against — when a site's NDA/privacy notice/safety-briefing version bumps, a visitor's prior consent does NOT carry forward automatically; they must re-consent to the new version before their next visit proceeds. Never grandfather old consent silently.
- Raw biometric captures deleted at earliest permitted point; protected templates encrypted, segregated from PII.
- Aadhaar numbers never stored; masked reference + verification result only.
- Synthetic test data only; never real IDs, biometrics, or customer visitor records.
- Cross-tenant access is a blocking defect in any component, including device commands and blob paths.
