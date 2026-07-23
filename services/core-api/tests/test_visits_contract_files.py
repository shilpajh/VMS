"""Contract-file presence check (US-11 Part B/file map). Mirrors
tests/test_openapi_contract_file.py's US-10 pattern -- this story's own
checked-in OpenAPI/AsyncAPI contract files, closing the same gap
proactively rather than deferring it the way US-10's identity.yaml was
deferred.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_FILE = REPO_ROOT / "packages" / "contracts" / "openapi" / "visits.yaml"
ASYNCAPI_FILE = REPO_ROOT / "packages" / "contracts" / "asyncapi" / "visit-checkin-dispatch.yaml"

EXPECTED_OPENAPI_PATH_FRAGMENTS = [
    "/public/portal/{tenant_slug}/visit-requests",
    "/visits",
    "/visits/{visit_id}",
    "/visits/{visit_id}/approve",
    "/visits/{visit_id}/deny",
]


def test_visits_openapi_contract_file_exists_and_is_valid_yaml() -> None:
    assert OPENAPI_FILE.exists()
    with OPENAPI_FILE.open() as fh:
        yaml.safe_load(fh)


def test_visits_openapi_contract_file_covers_all_new_endpoints() -> None:
    contract_text = OPENAPI_FILE.read_text()
    missing = [frag for frag in EXPECTED_OPENAPI_PATH_FRAGMENTS if frag not in contract_text]
    assert not missing, f"visits.yaml is missing expected path(s): {missing}"


def test_visit_checkin_dispatch_asyncapi_file_exists_and_is_valid_yaml() -> None:
    assert ASYNCAPI_FILE.exists()
    with ASYNCAPI_FILE.open() as fh:
        yaml.safe_load(fh)


def test_visit_checkin_dispatch_asyncapi_file_has_no_site_or_device_fields() -> None:
    """ADR-002 §1: this is a notification, not a device/panel command --
    site_id/device_id are reserved-nullable on the table but deliberately
    absent from THIS message's own payload schema."""
    contract_text = ASYNCAPI_FILE.read_text()
    assert "site_id" not in contract_text
    assert "device_id" not in contract_text
