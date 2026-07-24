# Smart VMS — Project Memory

Append-only log, one entry per completed story, written by `/document-story` (see step 3).
Future stories' GATHER step reads the last 5-10 entries here before touching anything else —
this is the cheapest context a story can get, cheaper than re-reading old specs or diffs.
Keep entries to 6-10 lines each; a rambling entry defeats the purpose.

<!-- Entries below this line, most recent last. -->

## US-11 — Website pre-registration visibility (2026-07-24)
Built: tenant-scoped `visits`+`outbox_messages` tables; public unauthenticated portal submission (rate-limited + Turnstile CAPTCHA); host approve/deny issuing check-in codes via transactional outbox; `view_visits` RBAC permission; full audit coverage. First visit-lifecycle transitions implemented (`Requested→{Registered,Denied}`).
Key decisions: ADR-002 (outbox + envelope encryption); check-in code = `token_urlsafe(24)`+SHA-256; retention (90d/7d) and consent framework are explicit placeholders pending human DPDP sign-off.
Gotchas: scope-creep incident — portal-UI commits landed post-Gate-1/post-first-verify-story, undetected until a later re-run; resolved via retroactive plan amendment + one-time design-gate review (see proposed skill change, not yet applied, in this story's PR). Real dedup cross-actor info-disclosure bug found and fixed mid-loop. Turnstile CAPTCHA-verify runs before rate-limiting (vendor call uncapped by our own limiter) — Should-fix, not blocking.
Depends on/blocks: stacked on `feature/US-10` (B1 fix independently verified fixed; both branches await Human Gate 2 release sign-off). Unblocks: relay-worker story, host-approval UI story, NULL-host reception triage.
Files: `services/core-api/app/api/portal.py`, `app/domain/visits/service.py`, `docs/architecture/adr/ADR-002-transactional-outbox-notification-contract.md`, `docs/reviews/US-11-review.md`.
