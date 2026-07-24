"""Pydantic v2 DTOs for the Visitor & Visits API surface (US-11).

Explicit DTOs at every boundary (backend-python.md). The portal response
(`PortalVisitRequestAccepted`) NEVER includes host/other-visit data -- it is
deliberately a uniform `tracking_reference`-only body regardless of whether
`host_hint` resolved to a real host (anti-enumeration, US-11 review, Notes).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PortalVisitRequestCreate(BaseModel):
    """Public, unauthenticated portal submission body (task 9)."""

    visitor_full_name: str = Field(min_length=1, max_length=255)
    contact_channel: Literal["email", "sms"]
    contact_value: str = Field(min_length=1, max_length=320)
    host_hint: str | None = Field(default=None, max_length=255)
    privacy_notice_acknowledged: bool = False
    privacy_notice_version: str = Field(min_length=1, max_length=32)
    turnstile_token: str = Field(min_length=1)


class PortalVisitRequestAccepted(BaseModel):
    """Uniform 202 response -- tracking_reference only, never host/other
    visit data, whether or not host_hint resolved (anti-enumeration)."""

    tracking_reference: str


class VisitOut(BaseModel):
    """Authenticated host/reception view of a visit (task 11; US-01 task 6
    adds `checked_in_at`). Deliberately never includes `checkin_code_hash`
    or any plaintext code -- the check-in credential never round-trips
    through this response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    status: str
    visitor_full_name: str
    contact_channel: str
    contact_value: str
    host_hint: str | None
    host_user_id: uuid.UUID | None
    tracking_reference: str
    denial_reason: str | None
    correlation_id: uuid.UUID
    decided_by_user_id: uuid.UUID | None
    decided_at: datetime | None
    checked_in_at: datetime | None = None
    created_at: datetime


class VisitDenyRequest(BaseModel):
    reason: str = Field(min_length=1)


class VisitCheckinRequest(BaseModel):
    """US-01, task 6. `checkin_code` is the plaintext QR-decoded bearer
    credential -- accepted only in the POST body, never a query/path
    param (never wants to land in server access logs or browser history)."""

    checkin_code: str = Field(min_length=1)
