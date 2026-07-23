---
name: biometric-provider-poc
description: Evaluate a face, fingerprint or iris vendor/device for Smart VMS before production adoption. Production coding for a modality is blocked until this POC passes.
argument-hint: "<vendor> <modality> <device>"
disable-model-invocation: true
---

# Mandatory gates

Input: $ARGUMENTS

Do not approve a provider until all gates are evidenced:

1. SDK validation on the actual target (Android bridge for tablet-attached; C#/Windows for edge-PC-attached).
2. Capture quality + liveness behavior tested, including spoof-attempt failure codes.
3. 1:1 verification accuracy tested against the agreed sample set; failure codes enumerated and mapped to the normalized result contract (result, score band, liveness outcome, failure code, provider reference).
4. Consent and audit linkage demonstrated end-to-end (versioned consent recorded before capture; audit event on every match decision).
5. Protected template handling: encryption, segregation from PII, and deletion verified — including provider-held data deletion terms.
6. Offline/cache restrictions verified: no raw capture persists on device or edge.
7. Manual fallback flow demonstrated when the device reports failure.
8. Complete the POC scorecard; builder + security-privacy-reviewer sign; a human compliance owner approves privacy items.

Rules: face starts with consented 1:1 + liveness (1:N/watchlist needs explicit tenant/legal enablement + human review). Fingerprint and iris stay gated behind their own device POC — do not reuse face evidence. Never work around missing vendor behavior with mocks presented as production-ready.

Output: docs/poc/<vendor>-<modality>-scorecard.md + an ADR if adopted. Loop budget: 3 cycles, then reject vendor/device or escalate.
