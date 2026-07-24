"""Task 3 (US-11): the frozen visit state-machine transition table
(app/domain/visits/state_machine.py). Only the two host transitions this
story wires (`host_approval`, `host_denial`) are reachable; every other
(status, trigger) pair -- including a direct jump to a later lifecycle
status like `checkin_verified` -- raises InvalidTransitionError. There is no
API route that accepts an arbitrary target status or trigger at all (that
route-level guarantee is exercised in tests/test_visits_api_routes.py,
Gherkin Scenario 5).
"""

from __future__ import annotations

import pytest

from app.domain.visits.state_machine import InvalidTransitionError, apply_transition


def test_requested_host_approval_transitions_to_registered() -> None:
    assert apply_transition("Requested", "host_approval") == "Registered"


def test_requested_host_denial_transitions_to_denied() -> None:
    assert apply_transition("Requested", "host_denial") == "Denied"


def test_checkin_verified_from_requested_is_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        apply_transition("Requested", "checkin_verified")


def test_direct_transition_to_checked_in_has_no_valid_trigger_from_requested() -> None:
    with pytest.raises(InvalidTransitionError):
        apply_transition("Requested", "checkin_verified")


@pytest.mark.parametrize(
    "status,trigger",
    [
        ("Registered", "host_approval"),
        ("Denied", "host_approval"),
        ("Denied", "host_denial"),
        ("CheckedIn", "checkout"),
        ("Held", "security_release"),
        ("Requested", "watchlist_match"),
        ("Requested", "unknown_trigger"),
    ],
)
def test_every_other_transition_not_wired_by_this_story_is_rejected(status, trigger) -> None:
    with pytest.raises(InvalidTransitionError):
        apply_transition(status, trigger)
