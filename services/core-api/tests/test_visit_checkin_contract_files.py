"""Task 8 (US-01): contract-file presence check, mirroring
tests/test_visits_contract_files.py's US-11 pattern for this story's own
new OpenAPI/AsyncAPI files plus the visit-lifecycle.yaml side_effects
amendment.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_FILE = REPO_ROOT / "packages" / "contracts" / "openapi" / "visits.yaml"
STATEMACHINE_FILE = REPO_ROOT / "packages" / "contracts" / "statemachine" / "visit-lifecycle.yaml"
CREDENTIAL_GRANT_FILE = REPO_ROOT / "packages" / "contracts" / "asyncapi" / "credential-grant-command.yaml"
ARRIVAL_NOTIFY_FILE = REPO_ROOT / "packages" / "contracts" / "asyncapi" / "visit-arrival-notify.yaml"
ADR_003_FILE = (
    REPO_ROOT / "docs" / "architecture" / "adr" / "ADR-003-credential-grant-command-contract.md"
)


def test_checkin_openapi_path_is_covered() -> None:
    assert "/visits/checkin" in OPENAPI_FILE.read_text()


def test_credential_grant_command_asyncapi_file_exists_and_is_valid_yaml() -> None:
    assert CREDENTIAL_GRANT_FILE.exists()
    with CREDENTIAL_GRANT_FILE.open() as fh:
        doc = yaml.safe_load(fh)
    assert doc["channels"]["visit.credential_grant.command"]


def _credential_grant_payload_properties() -> dict:
    with CREDENTIAL_GRANT_FILE.open() as fh:
        doc = yaml.safe_load(fh)
    return doc["components"]["messages"]["VisitCredentialGrantCommand"]["payload"]["properties"]


def test_credential_grant_command_has_no_zone_property() -> None:
    """ADR-003 Decision 1: zone-scoping deliberately stays out of the
    canonical device-command envelope's SCHEMA -- no placeholder string
    baked into a contract future commands reuse verbatim. (The word "zone"
    legitimately appears in this file's prose, explaining the omission --
    this checks the payload schema's actual property keys, not prose.)"""
    assert "zone" not in _credential_grant_payload_properties()


def test_credential_grant_command_has_site_and_device_properties() -> None:
    """Unlike visit-checkin-dispatch (a notification), this IS a device
    command -- site_id/device_id are present (both null in this story,
    reserved for the later edge-connector story)."""
    properties = _credential_grant_payload_properties()
    assert "site_id" in properties
    assert "device_id" in properties


def test_arrival_notify_asyncapi_file_exists_and_is_valid_yaml() -> None:
    assert ARRIVAL_NOTIFY_FILE.exists()
    with ARRIVAL_NOTIFY_FILE.open() as fh:
        doc = yaml.safe_load(fh)
    assert doc["channels"]["visit.arrival.notify"]


def test_visit_lifecycle_checkin_verified_has_credential_grant_side_effect() -> None:
    with STATEMACHINE_FILE.open() as fh:
        doc = yaml.safe_load(fh)
    (transition,) = [
        t
        for t in doc["transitions"]
        if t["from"] == "Registered" and t["trigger"] == "checkin_verified"
    ]
    assert transition["side_effects"] == ["credential_grant_command"]


def test_adr_003_exists() -> None:
    assert ADR_003_FILE.exists()


def test_arrival_notify_contract_documents_its_retention_purge_gate() -> None:
    """Task 10 (US-01): visit.arrival.notify is a NEW PII-bearing message
    type, even though it reuses the existing outbox_messages table. This
    doesn't add a new purge job (US-07 owns building that) -- it confirms,
    in the contract file itself, that this message type falls under the
    same standing PII-retention/purge GA gate docs/reviews/US-11-review.md
    already tracks for visit.checkin_code.dispatch, so a future /verify-story
    or /release-readiness pass finds the linkage without re-deriving it."""
    contract_text = ARRIVAL_NOTIFY_FILE.read_text()
    assert "GA gate" in contract_text
    assert "visit.checkin_code.dispatch" in contract_text
