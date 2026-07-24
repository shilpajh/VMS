"""US-11 remediation (verify-story, Track 2, item 3 -- fix verification).

HISTORY / WHAT THIS TEST USED TO PROVE:

This file used to be `test_portal_dedup_cross_actor_leak.py`. Before the fix,
`app/api/portal.py::_submission_dedup_key` derived the dedup key from
submission CONTENT only (`contact_value` + `host_hint`) -- the client-supplied
`Idempotency-Key` header VALUE was never part of the lookup, only its
*presence* was checked (`if idempotency_key:`). That meant an attacker who
knew or guessed a target visitor's `contact_value` (e.g. a corporate email in
a guessable format) and `host_hint` (e.g. a host's name from a LinkedIn post)
could resubmit that same content with their OWN arbitrary `Idempotency-Key`
value -- never the victim's real one, which they don't and shouldn't know --
and receive the ORIGINAL submitter's real `tracking_reference` back in the
202 response. This was a live, proven cross-visitor information-disclosure
defect (not a theoretical future risk), demonstrated by this exact test
(then named
`test_attacker_with_a_different_idempotency_key_value_can_still_fish_out_victims_tracking_reference`)
which PASSED while the vulnerability existed.

THE FIX: `_submission_dedup_key` now hashes the client's ACTUAL
`Idempotency-Key` header value together with submission content. A
resubmission only dedups if the client supplies the SAME key value AND the
SAME content. An attacker who doesn't know the victim's real key cannot
produce a matching hash no matter how well they guess the content.

THIS TEST NOW PROVES THE FIX HOLDS: the attacker's resubmission, using a
DIFFERENT Idempotency-Key value than the victim's, must create a SEPARATE
visit with its OWN distinct tracking_reference -- not the victim's.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import app
from app.security.captcha import FakeTurnstileVerifier, get_captcha_verifier
from app.security.rate_limit import get_per_ip_rate_limiter, get_per_tenant_rate_limiter
from tests.conftest import (
    AlwaysAllowRateLimiter,
    MIGRATOR_DSN,
    TestAppSessionLocal,
    insert_tenant,
)

VALID_CAPTCHA_TOKEN = "valid-test-token"


async def _override_get_session():
    async with TestAppSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture(autouse=True)
def override_dependencies(_migrated_schema):
    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_captcha_verifier] = lambda: FakeTurnstileVerifier(
        accept_tokens={VALID_CAPTCHA_TOKEN}
    )
    app.dependency_overrides[get_per_ip_rate_limiter] = lambda: AlwaysAllowRateLimiter()
    app.dependency_overrides[get_per_tenant_rate_limiter] = lambda: AlwaysAllowRateLimiter()
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    return TestClient(app)


def _set_public_slug(tenant_id: uuid.UUID, slug: str) -> None:
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET public_slug = %s WHERE id = %s", (slug, str(tenant_id)))
    finally:
        conn.close()


def _valid_submission_body(**overrides) -> dict:
    body = {
        "visitor_full_name": "Victim Visitor",
        "contact_channel": "email",
        "contact_value": "victim.visitor@known-corp.example",  # attacker knows/guesses this
        "host_hint": "rahul@acme",  # attacker knows/guesses this too (e.g. from a LinkedIn post)
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "v1",
        "purpose": "Business meeting",
        "group_type": "individual",
        "identity_verification_choice": "send_to_host",
        "turnstile_token": VALID_CAPTCHA_TOKEN,
    }
    body.update(overrides)
    return body


def test_attacker_with_a_different_idempotency_key_value_no_longer_fishes_out_victims_tracking_reference(
    client,
) -> None:
    """FIX VERIFIED: the dedup key is now bound to the client's ACTUAL
    Idempotency-Key header value, combined with submission content. An
    attacker who knows/guesses the victim's contact_value + host_hint, but
    supplies a DIFFERENT Idempotency-Key value than the victim's real one,
    must get back a NEW, DISTINCT tracking_reference -- not the victim's.

    (This test used to be named
    `test_attacker_with_a_different_idempotency_key_value_can_still_fish_out_victims_tracking_reference`
    and asserted the OPPOSITE -- that the attacker's forged key DID recover
    the victim's reference -- proving the exploit. See module docstring for
    the full history.)
    """
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)

    victim_body = _valid_submission_body()
    victim_response = client.post(
        f"/public/portal/{slug}/visit-requests",
        json=victim_body,
        headers={"Idempotency-Key": "victims-own-private-retry-key-never-shared"},
    )
    assert victim_response.status_code == 202
    victim_tracking_reference = victim_response.json()["tracking_reference"]

    # Attacker: same content (guessed), but a COMPLETELY DIFFERENT
    # Idempotency-Key value of their own choosing -- not the victim's.
    attacker_response = client.post(
        f"/public/portal/{slug}/visit-requests",
        json=victim_body,
        headers={"Idempotency-Key": "attacker-chose-this-value-arbitrarily"},
    )
    assert attacker_response.status_code == 202

    # Fix proven: the attacker does NOT recover the victim's real
    # tracking_reference -- a different Idempotency-Key value, even with
    # identical guessed content, is treated as a distinct submission.
    assert attacker_response.json()["tracking_reference"] != victim_tracking_reference, (
        "Regression: an attacker supplying a DIFFERENT Idempotency-Key value "
        "than the victim's should never be able to recover the victim's "
        "tracking_reference by guessing content (contact_value/host_hint) "
        "alone."
    )

    # Confirm this created a genuinely separate visit row, not a rejected
    # duplicate -- i.e. dedup correctly did NOT fire for a mismatched key.
    conn = psycopg2.connect(MIGRATOR_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM visits WHERE tenant_id = %s AND contact_value = %s",
                (str(tenant_id), victim_body["contact_value"]),
            )
            (count,) = cur.fetchone()
    finally:
        conn.close()
    assert count == 2  # victim's visit + attacker's own separate visit


def test_same_client_same_key_same_content_still_dedups(client) -> None:
    """Sanity check alongside the fix: the ORIGINAL intended behavior --
    the SAME client resubmitting with the SAME Idempotency-Key value and the
    SAME content -- must still hit the dedup path and get back the SAME
    tracking_reference. The fix must not overcorrect into never deduping."""
    tenant_id = insert_tenant("Acme", f"acme-entra-tid-{uuid.uuid4().hex[:8]}")
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    _set_public_slug(tenant_id, slug)

    body = _valid_submission_body()
    headers = {"Idempotency-Key": "the-real-clients-own-retry-key"}

    first = client.post(f"/public/portal/{slug}/visit-requests", json=body, headers=headers)
    second = client.post(f"/public/portal/{slug}/visit-requests", json=body, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["tracking_reference"] == second.json()["tracking_reference"]
