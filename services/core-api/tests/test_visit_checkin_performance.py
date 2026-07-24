"""US-01 verify-story (broader pass, item 2): PRD Technical AC — "scanning a
valid QR retrieves the visit in < 1s" — measured against `POST
/visits/checkin`.

This is a LOCAL-ENVIRONMENT measurement (single-process TestClient, local
Postgres on the same host as the test runner, one visit at a time, no
network hop, no load-balancer/App-Service cold start, no concurrent load) --
it is a floor-latency sanity check for the endpoint's own logic (guarded
UPDATE + two outbox inserts + one audit insert, all in one transaction), NOT
a substitute for a real staging/load-test measurement of the full deployed
path. Reported here as the actual measured number, per tests.md ("report
actual measurements... never round toward passing") -- this test does not
claim to satisfy "under agreed load" or "500 concurrent check-ins/site
cluster", which requires a real load-test environment (see US-01
verify-story report, item 2, for the explicit scope of what this does and
does not establish).

Uses fresh Registered visits per request (checkin_visit is single-use, so
timing N repeated calls against the SAME code/visit is not meaningful --
every call after the first would hit the uniform-404 path, not the
happy-path transition+outbox+audit work this AC is actually about).
"""

from __future__ import annotations

import statistics
import time
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_token_validator
from app.auth.entra import EntraTokenValidator, StaticJWKSProvider
from app.crypto.envelope import LocalEnvelopeKeyProvider, get_envelope_key_provider
from app.db.session import get_session
from app.main import app
from tests.conftest import MIGRATOR_DSN, TestAppSessionLocal, assign_role, insert_tenant, insert_user
from tests.support.entra_tokens import make_synthetic_idp
from tests.test_visit_checkin_route import _make_registered_visit_directly

AUDIENCE = "api://smart-vms-core-api-dev-placeholder"

# PRD Technical AC threshold under test.
QR_CHECKIN_THRESHOLD_SECONDS = 1.0

# Sample size: enough to report a meaningful p50/p95, small enough to stay
# well inside the bounded-loop runtime budget (AGENTS.md's 25-minute cap).
SAMPLE_SIZE = 30


async def _override_get_session():
    async with TestAppSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture()
def idp():
    return make_synthetic_idp()


@pytest.fixture(autouse=True)
def override_dependencies(idp, _migrated_schema):
    provider = StaticJWKSProvider({idp.kid: idp.public_key_pem})
    validator = EntraTokenValidator(jwks_provider=provider, audience=AUDIENCE)

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_token_validator] = lambda: validator
    app.dependency_overrides[get_envelope_key_provider] = lambda: LocalEnvelopeKeyProvider()
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    return TestClient(app)


def test_checkin_endpoint_latency_against_prd_threshold(client, idp) -> None:
    """Measures wall-clock latency of a full HTTP round trip through
    TestClient (ASGI in-process, no real network) -> POST /visits/checkin ->
    guarded UPDATE + 2 encrypted outbox inserts + 1 audit insert, against a
    real local Postgres (vms_test), one commit each. Reports actual p50/p95/
    max -- never rounds toward passing."""
    entra_tenant_id = f"acme-entra-tid-{uuid.uuid4().hex[:8]}"
    tenant_id = insert_tenant("Acme", entra_tenant_id)
    reception_oid = f"oid-reception-{uuid.uuid4().hex[:8]}"
    reception_id = insert_user(tenant_id, reception_oid)
    assign_role(tenant_id, reception_id, "reception_security")
    host_id = insert_user(tenant_id, f"oid-host-{uuid.uuid4().hex[:8]}")
    token = idp.issue_token(tid=entra_tenant_id, aud=AUDIENCE, oid=reception_oid)
    headers = {"Authorization": f"Bearer {token}"}

    durations: list[float] = []
    for _ in range(SAMPLE_SIZE):
        # Fresh Registered visit + code per iteration -- checkin_visit is
        # single-use by design (guarded UPDATE), so a second call against
        # the same code would measure the uniform-404 rejection path
        # instead of the happy-path work this AC is about.
        _visit_id, code = _make_registered_visit_directly(tenant_id, host_id)

        start = time.perf_counter()
        response = client.post("/visits/checkin", headers=headers, json={"checkin_code": code})
        elapsed = time.perf_counter() - start

        assert response.status_code == 200
        durations.append(elapsed)

    p50 = statistics.median(durations)
    p95 = statistics.quantiles(durations, n=20)[18]  # 95th percentile
    worst = max(durations)

    print(
        f"\n[US-01 perf] POST /visits/checkin latency over {SAMPLE_SIZE} calls "
        f"(local TestClient + local Postgres, single-process, no concurrency): "
        f"p50={p50 * 1000:.1f}ms p95={p95 * 1000:.1f}ms max={worst * 1000:.1f}ms "
        f"threshold={QR_CHECKIN_THRESHOLD_SECONDS * 1000:.0f}ms"
    )

    # Report the actual number regardless of outcome -- this assertion is
    # the executable form of the PRD AC, not a rounding-toward-passing gate.
    assert p95 < QR_CHECKIN_THRESHOLD_SECONDS, (
        f"p95 latency {p95:.3f}s exceeds the PRD's < 1s QR check-in retrieval "
        f"threshold (measured over {SAMPLE_SIZE} calls; max={worst:.3f}s)"
    )
