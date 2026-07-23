"""QA-added (verify-story, US-11): probes whether the public portal's
`Idempotency-Key` dedup mechanism is bound to the CLIENT'S ACTUAL header
value, or only to submission CONTENT (contact_value + host_hint).

`app/api/portal.py::_submission_dedup_key` derives the dedup key from
`contact_value` + `host_hint` only -- the client-supplied `Idempotency-Key`
header value itself is never part of the lookup, only its *presence* is
checked (`if idempotency_key:`). This means the mechanism does not actually
implement "the same client safely retries with the same key" semantics; it
implements "anyone who submits the same content, with ANY non-empty
Idempotency-Key header of their own choosing, gets back the ORIGINAL
submitter's tracking_reference" -- as long as the original submission also
included some Idempotency-Key header.

This is a real gap: an attacker who knows or guesses a target visitor's
contact_value (e.g. a corporate email address in a guessable format) and the
host_hint they named can retrieve that visitor's tracking_reference by
resubmitting the same content with a DIFFERENT, self-chosen Idempotency-Key
value -- not the value the original submitter used (which the attacker does
not and should not know). This defeats the anti-enumeration intent behind
"tenant-scoped, content-hashed" dedup (US-11 review, Should-fix #1): the
review's threat model was "a guessed/reused raw client key must not fish out
an unrelated submission," but the implementation instead makes the *key
value* irrelevant and the *content* the entire secret -- and contact_value/
host_hint are frequently guessable/enumerable, unlike a properly-scoped
idempotency key.

Reported as a finding, not fixed here (QA does not patch application code).
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
        "turnstile_token": VALID_CAPTCHA_TOKEN,
    }
    body.update(overrides)
    return body


def test_attacker_with_a_different_idempotency_key_value_can_still_fish_out_victims_tracking_reference(
    client,
) -> None:
    """FINDING: the dedup key is derived purely from submission content, not
    from the client's actual Idempotency-Key header value. An attacker who
    knows/guesses the victim's contact_value + host_hint, and supplies their
    OWN arbitrary Idempotency-Key (never the victim's real one, which they
    don't know), still gets back the victim's real tracking_reference.
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

    # This assertion demonstrates the gap: the attacker recovers the
    # victim's real tracking_reference despite never having known or
    # supplied the victim's actual idempotency key.
    assert attacker_response.json()["tracking_reference"] == victim_tracking_reference, (
        "Gap confirmed: dedup matched on guessed CONTENT alone; the "
        "Idempotency-Key header's actual VALUE was never checked, only its "
        "presence. This lets anyone who can guess a victim's "
        "contact_value+host_hint retrieve that visitor's tracking "
        "reference, without ever knowing the victim's real idempotency key."
    )
