"""Task 8 (US-13a): contract-file presence/validity for the OTP + tracking
surfaces and ADR-004 (mirrors test_visit_checkin_contract_files.py).
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI = REPO_ROOT / "packages" / "contracts" / "openapi" / "visits.yaml"
OTP_DISPATCH = REPO_ROOT / "packages" / "contracts" / "asyncapi" / "portal-otp-dispatch.yaml"
ADR_004 = (
    REPO_ROOT / "docs" / "architecture" / "adr"
    / "ADR-004-portal-contact-verification-and-tracking-lookup.md"
)


def test_openapi_covers_new_portal_paths() -> None:
    with OPENAPI.open() as fh:
        doc = yaml.safe_load(fh)
    paths = set(doc["paths"])
    assert "/public/portal/{tenant_slug}/otp/request" in paths
    assert "/public/portal/{tenant_slug}/otp/verify" in paths
    assert "/public/portal/{tenant_slug}/visit-requests/{tracking_reference}" in paths


def test_openapi_submission_requires_new_fields() -> None:
    with OPENAPI.open() as fh:
        doc = yaml.safe_load(fh)
    required = set(doc["components"]["schemas"]["PortalVisitRequestCreate"]["required"])
    assert {"purpose", "group_type", "identity_verification_choice"} <= required


def test_tracking_status_schema_has_no_checkin_code_or_resolved_host() -> None:
    with OPENAPI.open() as fh:
        doc = yaml.safe_load(fh)
    props = set(doc["components"]["schemas"]["PortalTrackingStatus"]["properties"])
    assert props == {"status", "visitor_full_name", "host_hint"}
    assert "checkin_code" not in props
    assert "host_display_name" not in props


def test_otp_dispatch_asyncapi_valid_and_has_send_gate() -> None:
    with OTP_DISPATCH.open() as fh:
        doc = yaml.safe_load(fh)
    assert doc["channels"]["portal.otp.dispatch"]
    props = doc["components"]["messages"]["PortalOtpDispatch"]["payload"]["properties"]
    assert "otp_code" in props and "contact_value" in props
    # send-gate + never-log discipline documented
    text = OTP_DISPATCH.read_text()
    assert "x-send-gate" in text
    assert "superseded" in text


def test_adr_004_exists() -> None:
    assert ADR_004.exists()
