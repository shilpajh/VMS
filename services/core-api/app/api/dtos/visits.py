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

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PortalOtpRequestCreate(BaseModel):
    """US-13a: request an OTP for a contact channel. Consent is captured
    HERE (decision 3) -- before any PII is stored/dispatched."""

    contact_channel: Literal["email", "sms"]
    contact_value: str = Field(min_length=1, max_length=320)
    privacy_notice_acknowledged: bool = False
    privacy_notice_version: str = Field(min_length=1, max_length=32)
    turnstile_token: str = Field(min_length=1)


class PortalOtpRequestAccepted(BaseModel):
    """Uniform 202 -- generic, never reveals whether the contact was known
    or had a prior OTP (anti-enumeration)."""

    detail: str = "if the contact is valid, a code has been sent"


class PortalOtpVerifyRequest(BaseModel):
    """US-13a: verify an OTP, receive a single-use verification token."""

    contact_channel: Literal["email", "sms"]
    contact_value: str = Field(min_length=1, max_length=320)
    otp_code: str = Field(min_length=1, max_length=12)
    turnstile_token: str = Field(min_length=1)


class PortalOtpVerifyAccepted(BaseModel):
    """The plaintext verification token -- transient, client-held only until
    submission (mirrors the check-in code's handling)."""

    verification_token: str


class PortalVisitRequestCreate(BaseModel):
    """Public, unauthenticated portal submission body (US-11 task 9;
    US-13a adds purpose/group/identity-choice + the verification token)."""

    visitor_full_name: str = Field(min_length=1, max_length=255)
    contact_channel: Literal["email", "sms"]
    contact_value: str = Field(min_length=1, max_length=320)
    host_hint: str | None = Field(default=None, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    group_type: Literal["individual", "group"]
    expected_group_size: int | None = Field(default=None, ge=1)
    identity_verification_choice: Literal["upload_now", "send_to_host"]
    # Required only when settings.portal_otp_required is on (enforced in the
    # endpoint, not here, so the flag-off path keeps US-11 behavior).
    verification_token: str | None = Field(default=None)
    # US-11 consent fields -- still used on the flag-OFF path (no token); on
    # the flag-ON path the version comes from the verified row instead.
    privacy_notice_acknowledged: bool = False
    privacy_notice_version: str = Field(min_length=1, max_length=32)
    turnstile_token: str = Field(min_length=1)

    @model_validator(mode="after")
    def _group_size_required_for_group(self) -> "PortalVisitRequestCreate":
        if self.group_type == "group" and self.expected_group_size is None:
            raise ValueError("expected_group_size is required when group_type is 'group'")
        return self


class PortalVisitRequestAccepted(BaseModel):
    """Uniform 202 response -- tracking_reference only, never host/other
    visit data, whether or not host_hint resolved (anti-enumeration)."""

    tracking_reference: str


class PortalTrackingStatus(BaseModel):
    """US-13a tracking-lookup response. Status + the visitor's OWN submitted
    details only -- `host_hint` is the string the visitor typed, NEVER the
    resolved employee's display_name, and NEVER a check-in code (decision 2;
    US-13 review B2)."""

    status: str
    visitor_full_name: str
    host_hint: str | None


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
