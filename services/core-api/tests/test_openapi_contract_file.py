"""Contract-file presence check (US-10 /verify-story gap fill).

The approved plan's file map (docs/plans/US-10.md, Part C) names
`packages/contracts/openapi/identity.yaml` as a NEW checked-in contract file
covering `/me`, `/roles`, `/permissions`, `/tenants/{id}/users*` -- per
`.claude/rules/contracts.md` ("OpenAPI for REST ... contract tests gate
merges", "Contract changes require a contract ticket + owner approval from
each consuming component"). This is what lets other components (web,
kiosk, edge) generate typed clients against a stable, reviewed contract
instead of each one independently trusting whatever FastAPI happens to
auto-generate at runtime.

This test intentionally fails until that file exists and describes at
least the endpoints this story introduces -- it is not testing application
code, it is testing whether the plan's own file-map deliverable was
produced. Per verify-story's rules, a real gap must be captured as an
executable (here: currently failing) test and reported, not silently
patched over.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_FILE = REPO_ROOT / "packages" / "contracts" / "openapi" / "identity.yaml"

EXPECTED_PATH_FRAGMENTS = [
    "/me",
    "/roles",
    "/permissions",
    "/tenants/{tenant_id}/users",
]


def test_identity_openapi_contract_file_exists() -> None:
    assert CONTRACT_FILE.exists(), (
        f"{CONTRACT_FILE} does not exist. The US-10 plan's file map "
        "(docs/plans/US-10.md, Part C) names this as a new checked-in "
        "OpenAPI contract file for /me, /roles, /permissions, and the "
        "/tenants/{tenant_id}/users* endpoints -- required per "
        ".claude/rules/contracts.md ('OpenAPI for REST ... contract tests "
        "gate merges'). Only the live FastAPI-generated schema exists "
        "today (app.openapi()); nothing is checked in for other "
        "components (web/kiosk/edge) to consume or for a contract-diff "
        "review to gate on."
    )


@pytest.mark.skipif(
    not CONTRACT_FILE.exists(), reason="contract file does not exist yet (see test above)"
)
def test_identity_openapi_contract_file_covers_all_new_endpoints() -> None:
    contract_text = CONTRACT_FILE.read_text()
    missing = [frag for frag in EXPECTED_PATH_FRAGMENTS if frag not in contract_text]
    assert not missing, f"identity.yaml is missing expected path(s): {missing}"
