"""Guards for the `checkin_verified` transition (US-01, task 3).

`packages/contracts/statemachine/visit-lifecycle.yaml`'s `checkin_verified`
transition (`Registered -> CheckedIn`) names three guards:
`identity_verified`, `watchlist_clear`, `within_visit_window`. Each is its
own named function here -- not inlined at the guard-check call site in
`app/domain/visits/service.py` -- so each has exactly one place a later
story replaces when its real implementation lands.
"""

from __future__ import annotations

from datetime import datetime


def identity_verified_by_code() -> bool:
    """Implements the contract's `identity_verified` guard for the QR-code
    path only (US-01 scope). Possession of a check-in code whose hash
    matches a `Registered` visit's `checkin_code_hash` (verified by the
    guarded UPDATE in `checkin_visit()`, not here) IS the identity proof for
    this story -- there is no face/fingerprint/iris verification (US-01
    plan, Out of scope). Always `True`: by the time this is called, the
    hash match has already succeeded."""
    return True


def watchlist_clear() -> bool:
    """STUB -- implements the contract's `watchlist_clear` guard as an
    always-`True` placeholder. No watchlist data source exists anywhere in
    this system yet (PRD 3.5 is a separate, not-yet-built story). This is a
    named, greppable stub, never an inline `True` at the call site, and
    returning `True` here does NOT mean "watchlist screening was performed
    and cleared" -- it means no screening happens at all yet. See US-01
    plan, Part A Risks: this is a release-blocker for any release claiming
    automated watchlist coverage, and the separate `Registered -> Held`
    (`watchlist_match`) contract edge is ALSO unwired by this story -- both
    facts belong together, not just this stub in isolation."""
    return True


def within_visit_window(checkin_code_expires_at: datetime | None, *, now: datetime) -> bool:
    """Implements the contract's `within_visit_window` guard. Reads
    `visits.checkin_code_expires_at` only -- never `outbox_messages`, which
    is a dispatch artifact, not the domain's source of truth (US-01 plan,
    Part A Risks). This is a known-interim substitution: the column denotes
    the deadline to *arrive and use the code*, not a real scheduled
    visit-arrival window (no story has built one yet).

    `None` fails closed (mirrors the guarded UPDATE's `NULL > :now` SQL
    behavior in `checkin_visit()`) -- a pre-migration row with no persisted
    expiry is treated as expired, never as unbounded."""
    if checkin_code_expires_at is None:
        return False
    return checkin_code_expires_at > now
