---
paths:
  - "apps/kiosk/**/*.dart"
---

# Flutter kiosk rules
- No business policy on the device; capture, display, queue only.
- Native platform channels are thin typed bridges to device SDKs (USB/NFC/camera/biometric) — no logic in the bridge.
- Offline: encrypted minimal cache, idempotency-keyed event queue, only pre-approved flows during outage, reconcile without duplicates on reconnect.
- Raw biometric captures never persist beyond capture-and-transmit; never in cache, logs, or crash reports.
- Versioned consent linked to the visit before any biometric capture.
- Multilingual (Hindi + regional + English); kiosk lock-task compatible; WCAG-compliant.
