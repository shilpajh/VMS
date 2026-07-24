"""Task 3 (US-01): app/domain/visits/guards.py -- the three named guards
`visit-lifecycle.yaml`'s `checkin_verified` transition requires
(`identity_verified`, `watchlist_clear`, `within_visit_window`).

`watchlist_clear` is a deliberate always-True stub (no watchlist data
source exists anywhere in the system yet -- US-01 plan, Part A Risks and
Out of scope). This test asserts it is a NAMED, CALLABLE stub -- not an
inline `True` literal buried in a conditional -- so a future watchlist
story replacing it has one obvious call site to change, and so nothing
here can be mistaken for "watchlist screening was performed."
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.visits.guards import (
    identity_verified_by_code,
    watchlist_clear,
    within_visit_window,
)


def test_identity_verified_by_code_is_true_for_a_hash_matched_visit() -> None:
    # Possession of a hash-matched check-in code IS the identity proof for
    # this story (no face/fingerprint/iris verification -- US-01 scope).
    assert identity_verified_by_code() is True


def test_watchlist_clear_stub_always_returns_true() -> None:
    assert watchlist_clear() is True


def test_watchlist_clear_is_a_named_function_not_an_inline_literal() -> None:
    """Greppable-marker requirement: the stub must be its own callable, not
    `True` written directly at the guard-check call site."""
    assert callable(watchlist_clear)
    assert watchlist_clear.__name__ == "watchlist_clear"


def test_within_visit_window_true_before_expiry() -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    assert within_visit_window(expires_at, now=datetime.now(timezone.utc)) is True


def test_within_visit_window_false_after_expiry() -> None:
    expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert within_visit_window(expires_at, now=datetime.now(timezone.utc)) is False


def test_within_visit_window_fails_closed_on_null_expiry() -> None:
    """A NULL checkin_code_expires_at (e.g. a pre-migration row) must fail
    closed, not open -- mirrors the guarded UPDATE's `NULL > :now` SQL
    behavior (US-01 plan, Part A Risks)."""
    assert within_visit_window(None, now=datetime.now(timezone.utc)) is False
