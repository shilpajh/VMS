"""Visit lifecycle state machine (US-11, task 3).

A frozen `(from_status, trigger) -> to_status` map, sourced from
`packages/contracts/statemachine/visit-lifecycle.yaml` -- this story only
wires the two portal/host transitions it implements
(`Requested -> Registered` via `host_approval`, `Requested -> Denied` via
`host_denial`). Every other (status, trigger) pair -- including any attempt
to jump directly to a later lifecycle status -- is rejected.

Enforced in the domain layer (this module) AND in a DB transaction (the
guarded conditional UPDATE in app/domain/visits/service.py, `WHERE
status = 'Requested'`) -- never only here, per backend-python.md ("Enforce
visit state transitions in the domain layer + DB transaction").
"""

from __future__ import annotations


class InvalidTransitionError(Exception):
    """Raised for any (status, trigger) pair not in the frozen transition
    table. API routes map this to 409 Conflict (visit-lifecycle.yaml's
    contract; US-11 review Should-fix #6 concrete mapping)."""


# Only the transitions this story implements. Every other lifecycle edge in
# visit-lifecycle.yaml (e.g. Registered -> CheckedIn via checkin_verified,
# Held -> CheckedIn via security_release) is later stories' work -- adding a
# row here is the only way to "reach" a new transition; there is no generic
# "apply any trigger" code path anywhere in this story's API surface.
_TRANSITIONS: dict[tuple[str, str], str] = {
    ("Requested", "host_approval"): "Registered",
    ("Requested", "host_denial"): "Denied",
}


def apply_transition(from_status: str, trigger: str) -> str:
    """Returns the resulting status for a valid (from_status, trigger) pair,
    or raises InvalidTransitionError."""
    try:
        return _TRANSITIONS[(from_status, trigger)]
    except KeyError:
        raise InvalidTransitionError(
            f"no transition wired for status={from_status!r} trigger={trigger!r}"
        ) from None
