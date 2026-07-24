from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Request-path connection: the non-superuser, RLS-subject `vms_app` role
    # (ADR-001 §1). The running application NEVER connects as the `vms`
    # superuser or as `vms_migrator` — only migrations/ops scripts do.
    database_url: str = "postgresql+asyncpg://vms_app:dev-only-not-for-real-secrets@localhost:5432/vms"
    # Migration/ops connection: the separate BYPASSRLS `vms_migrator` role
    # (ADR-001 §1/N3), used only by Alembic and scripts/bootstrap_tenant.py —
    # never the request path. Sync driver (psycopg2), per alembic/env.py.
    migrations_database_url: str = (
        "postgresql://vms_migrator:dev-only-not-for-real-secrets@localhost:5432/vms"
    )
    redis_url: str = "redis://localhost:6379/0"

    # This API's Entra App ID / App ID URI. Bearer tokens whose `aud` claim
    # doesn't exactly match this are rejected (ADR-001 §5) -- placeholder
    # for local dev, never a real Entra registration; production value comes
    # from Key Vault / app configuration, never checked in.
    entra_api_audience: str = "api://smart-vms-core-api-dev-placeholder"

    # --- US-11: public portal guardrails + outbox envelope encryption ---
    # Cloudflare Turnstile secret key (siteverify). Placeholder for local
    # dev -- never a real Turnstile account in this environment; production
    # value comes from Key Vault, never checked in (US-11 review, Notes).
    turnstile_secret_key: str = "dev-only-turnstile-secret-placeholder"
    # Azure Key Vault key id/version used to envelope-encrypt outbox
    # payloads (ADR-002 §5). Placeholder -- there is no real Key Vault
    # access in this environment; app.crypto.envelope's production wiring
    # is never exercised by any test here.
    envelope_encryption_key_ref: str = "dev-only-key-vault-key-ref-placeholder"

    # Public portal rate limiting (app/security/rate_limit.py). Per-IP:
    # sustained ~5/min, burst up to 10. Per-tenant-slug: sustained ~60/min
    # (US-11 plan/API contract delta).
    portal_rate_limit_per_ip_capacity: int = 10
    portal_rate_limit_per_ip_refill_per_minute: float = 5.0
    portal_rate_limit_per_tenant_capacity: int = 60
    portal_rate_limit_per_tenant_refill_per_minute: float = 60.0
    # X-Forwarded-For is trusted ONLY behind a real trusted gateway/proxy
    # that sets it -- default false for local dev, where a client could set
    # this header itself to spoof its source IP (US-11 plan, task 7).
    trust_forwarded_for: bool = False

    # --- US-13a: portal OTP contact verification + tracking lookup ---
    # Key-Vault-managed HMAC secret for hashing the low-entropy OTP and the
    # verification token (app/crypto/hmac_hash.py, ADR-004). Placeholder for
    # local dev -- never a real Key Vault here; production value from Key
    # Vault, never checked in.
    otp_hmac_key_ref: str = "dev-only-otp-hmac-key-placeholder"
    # Config-gate (US-13a decision 1): when False, the portal keeps US-11's
    # behavior (no verification_token required); when True, submission
    # requires a validated OTP token. Default off until the SMS/email relay
    # worker exists to actually deliver codes.
    portal_otp_required: bool = False
    # Dedicated rate-limit buckets for the OTP endpoints -- stricter than,
    # and independent of, the submission buckets (US-13a, ADR-004). Concrete
    # starting values; tunable via config without a code change.
    otp_request_per_ip_capacity: int = 5
    otp_request_per_ip_refill_per_minute: float = 1.0
    otp_request_per_contact_capacity: int = 3
    otp_request_per_contact_refill_per_minute: float = 0.2  # ~1 per 5 min
    otp_verify_per_ip_capacity: int = 10
    otp_verify_per_ip_refill_per_minute: float = 2.0
    # Dedicated tracking-lookup buckets -- separate Redis namespace from
    # submission so a lookup flood cannot starve legitimate submissions
    # (US-13 review Should-fix #5).
    tracking_lookup_per_ip_capacity: int = 20
    tracking_lookup_per_ip_refill_per_minute: float = 5.0
    tracking_lookup_per_tenant_capacity: int = 120
    tracking_lookup_per_tenant_refill_per_minute: float = 60.0
    # OTP / verification-token lifetimes (ADR-004).
    otp_ttl_seconds: int = 300  # 5 min
    otp_max_attempts: int = 5
    verification_token_ttl_seconds: int = 900  # 15 min


settings = Settings()
