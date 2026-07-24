"""Task 4 (US-13a): OTP domain module (app/domain/portal/otp.py).

Covers the security-critical logic directly (not through HTTP): generation,
HMAC hashing, supersede-on-reissue, race-safe guarded-attempt constant-work
verify, and single-use contact-scoped verification-token issue/consume.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.crypto.hmac_hash import LocalHmacKeyProvider
from app.domain.portal.otp import (
    InvalidOtpError,
    InvalidVerificationTokenError,
    consume_verification_token,
    generate_otp_code,
    issue_otp,
    verify_otp_and_issue_token,
)
from app.models import PortalContactVerification
from tests.conftest import TestAppSessionLocal, insert_tenant, set_tenant_context

CHANNEL = "email"


@pytest.fixture()
def hmac_provider():
    return LocalHmacKeyProvider(key=b"otp-domain-test-key")


def test_generate_otp_is_six_digits() -> None:
    for _ in range(50):
        code = generate_otp_code()
        assert len(code) == 6
        assert code.isdigit()


async def _mk_tenant(session) -> uuid.UUID:
    tenant_id = insert_tenant("Acme", f"acme-entra-{uuid.uuid4().hex[:8]}")
    await set_tenant_context(session, tenant_id)
    return tenant_id


async def test_issue_otp_persists_hashed_never_plaintext(app_session, hmac_provider) -> None:
    tenant_id = await _mk_tenant(app_session)
    row, code = await issue_otp(
        app_session,
        tenant_id=tenant_id,
        contact_channel=CHANNEL,
        contact_value="jane@example.com",
        privacy_notice_version="v1",
        hmac_provider=hmac_provider,
    )
    assert len(code) == 6
    assert row.otp_hash != code
    assert code not in row.otp_hash


async def test_reissue_supersedes_prior_rows_for_same_contact(app_session, hmac_provider) -> None:
    tenant_id = await _mk_tenant(app_session)
    first, _ = await issue_otp(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", privacy_notice_version="v1", hmac_provider=hmac_provider,
    )
    second, _ = await issue_otp(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", privacy_notice_version="v1", hmac_provider=hmac_provider,
    )
    refreshed_first = (
        await app_session.execute(
            select(PortalContactVerification).where(PortalContactVerification.id == first.id)
        )
    ).scalar_one()
    assert refreshed_first.superseded is True
    assert second.superseded is False


async def test_verify_correct_code_issues_token(app_session, hmac_provider) -> None:
    tenant_id = await _mk_tenant(app_session)
    _, code = await issue_otp(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", privacy_notice_version="v1", hmac_provider=hmac_provider,
    )
    token = await verify_otp_and_issue_token(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", otp_code=code, hmac_provider=hmac_provider,
    )
    assert isinstance(token, str) and len(token) > 20


async def test_five_wrong_attempts_then_correct_all_fail(app_session, hmac_provider) -> None:
    tenant_id = await _mk_tenant(app_session)
    _, code = await issue_otp(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", privacy_notice_version="v1", hmac_provider=hmac_provider,
    )
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(InvalidOtpError):
            await verify_otp_and_issue_token(
                app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
                contact_value="jane@example.com", otp_code=wrong, hmac_provider=hmac_provider,
            )
    # 6th attempt with the CORRECT code still fails -- attempts exhausted.
    with pytest.raises(InvalidOtpError):
        await verify_otp_and_issue_token(
            app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
            contact_value="jane@example.com", otp_code=code, hmac_provider=hmac_provider,
        )


async def test_supersede_caps_guesses_per_contact_not_per_row(app_session, hmac_provider) -> None:
    """N reissues must NOT multiply the guess budget: only the current
    (non-superseded) row is verifiable, so a code from a superseded row
    never verifies regardless of how many rows exist."""
    tenant_id = await _mk_tenant(app_session)
    _, old_code = await issue_otp(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", privacy_notice_version="v1", hmac_provider=hmac_provider,
    )
    _, new_code = await issue_otp(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", privacy_notice_version="v1", hmac_provider=hmac_provider,
    )
    # The superseded code no longer verifies...
    with pytest.raises(InvalidOtpError):
        await verify_otp_and_issue_token(
            app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
            contact_value="jane@example.com", otp_code=old_code, hmac_provider=hmac_provider,
        )
    # ...but the current one does.
    token = await verify_otp_and_issue_token(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", otp_code=new_code, hmac_provider=hmac_provider,
    )
    assert token


async def test_expired_otp_does_not_verify(app_session, hmac_provider) -> None:
    tenant_id = await _mk_tenant(app_session)
    row, code = await issue_otp(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", privacy_notice_version="v1", hmac_provider=hmac_provider,
    )
    row.otp_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await app_session.flush()
    with pytest.raises(InvalidOtpError):
        await verify_otp_and_issue_token(
            app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
            contact_value="jane@example.com", otp_code=code, hmac_provider=hmac_provider,
        )


async def test_verify_no_pending_otp_fails_uniformly(app_session, hmac_provider) -> None:
    tenant_id = await _mk_tenant(app_session)
    with pytest.raises(InvalidOtpError):
        await verify_otp_and_issue_token(
            app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
            contact_value="never-requested@example.com", otp_code="123456", hmac_provider=hmac_provider,
        )


async def test_verify_runs_identical_statement_count_for_no_otp_and_wrong_code(
    app_session, hmac_provider, monkeypatch
) -> None:
    """Constant-work regression: 'no pending OTP' and 'wrong code' failure
    paths must issue the same number of SQL statements (SELECT + one
    attempt-increment UPDATE, no early-return), closing the timing oracle
    (US-13 review Should-fix #4)."""
    import app.domain.portal.otp as otp_mod

    async def count_statements(contact_value: str, otp_code: str, tenant_id) -> int:
        executed: list[str] = []
        orig = app_session.execute

        async def counting(stmt, *a, **k):
            executed.append(type(stmt).__name__)
            return await orig(stmt, *a, **k)

        monkeypatch.setattr(app_session, "execute", counting)
        try:
            with pytest.raises(InvalidOtpError):
                await otp_mod.verify_otp_and_issue_token(
                    app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
                    contact_value=contact_value, otp_code=otp_code, hmac_provider=hmac_provider,
                )
        finally:
            monkeypatch.setattr(app_session, "execute", orig)
        return len(executed)

    tenant_id = await _mk_tenant(app_session)
    _, code = await issue_otp(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", privacy_notice_version="v1", hmac_provider=hmac_provider,
    )
    wrong = "111111" if code == "000000" else "000000"

    wrong_code_stmts = await count_statements("jane@example.com", wrong, tenant_id)
    no_otp_stmts = await count_statements("never-requested@example.com", "123456", tenant_id)
    assert wrong_code_stmts == no_otp_stmts


async def test_token_is_single_use_and_contact_scoped(app_session, hmac_provider) -> None:
    tenant_id = await _mk_tenant(app_session)
    _, code = await issue_otp(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", privacy_notice_version="v1", hmac_provider=hmac_provider,
    )
    token = await verify_otp_and_issue_token(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", otp_code=code, hmac_provider=hmac_provider,
    )
    # A token verified for jane cannot be consumed against a different contact.
    with pytest.raises(InvalidVerificationTokenError):
        await consume_verification_token(
            app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
            contact_value="someone-else@example.com", verification_token=token, hmac_provider=hmac_provider,
        )
    # Correct contact consumes it and returns the privacy version...
    version = await consume_verification_token(
        app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
        contact_value="jane@example.com", verification_token=token, hmac_provider=hmac_provider,
    )
    assert version == "v1"
    # ...and a replay of the now-consumed token fails.
    with pytest.raises(InvalidVerificationTokenError):
        await consume_verification_token(
            app_session, tenant_id=tenant_id, contact_channel=CHANNEL,
            contact_value="jane@example.com", verification_token=token, hmac_provider=hmac_provider,
        )


async def test_concurrent_token_consume_only_one_succeeds() -> None:
    """Race-safety: two concurrent consumes of the same token -> exactly one
    succeeds. Independent sessions/connections for real DB-level concurrency."""
    hmac_provider = LocalHmacKeyProvider(key=b"otp-domain-test-key")
    tenant_id = insert_tenant("Acme", f"acme-entra-{uuid.uuid4().hex[:8]}")

    async with TestAppSessionLocal() as setup:
        await set_tenant_context(setup, tenant_id)
        _, code = await issue_otp(
            setup, tenant_id=tenant_id, contact_channel=CHANNEL,
            contact_value="jane@example.com", privacy_notice_version="v1", hmac_provider=hmac_provider,
        )
        token = await verify_otp_and_issue_token(
            setup, tenant_id=tenant_id, contact_channel=CHANNEL,
            contact_value="jane@example.com", otp_code=code, hmac_provider=hmac_provider,
        )
        await setup.commit()

    async def _attempt():
        async with TestAppSessionLocal() as session:
            await set_tenant_context(session, tenant_id)
            try:
                await consume_verification_token(
                    session, tenant_id=tenant_id, contact_channel=CHANNEL,
                    contact_value="jane@example.com", verification_token=token, hmac_provider=hmac_provider,
                )
                await session.commit()
                return "ok"
            except InvalidVerificationTokenError:
                await session.rollback()
                return "conflict"

    results = await asyncio.gather(_attempt(), _attempt())
    assert sorted(results) == ["conflict", "ok"]
