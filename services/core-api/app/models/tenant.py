import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Reserved sentinel tenant (ADR-001 §2/§4): a fixed, well-known UUID so that
# platform-level actions (currently only `tenant.created`, emitted by the ops
# bootstrap script) always have a real, non-null tenant to attribute audit
# rows to. This keeps `tenant_id NOT NULL` an absolute invariant everywhere,
# including on audit_events and on the bootstrap of `tenants` itself. It is
# NOT a real Entra tenant — its `entra_tenant_id` value can never match a
# real Entra `tid` claim, so no token can ever resolve to it.
PLATFORM_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
PLATFORM_TENANT_ENTRA_TENANT_ID = "platform-sentinel-no-entra-tenant"

TENANT_STATUSES = ("active", "suspended")


class Tenant(Base):
    """The tenant registry / isolation root. Not tenant_id-scoped: its own
    `id` *is* the tenant. RLS does not apply here — this table is the
    discriminator source (ADR-001 §2)."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entra_tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended')", name="ck_tenants_status"
        ),
    )
