// Typed fetch wrappers for the public portal endpoints (US-13b), matching
// US-13a's OpenAPI contract (packages/contracts/openapi/visits.yaml). Request
// shapes live here in one place so the form/tracking components can't drift
// from the server contract (the drift that broke the US-11 form against the
// US-13a backend). The server decides everything; these only shape the call.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

// PortalVisitRequestCreate (US-13a). purpose/group_type/identity_verification_
// choice are REQUIRED by the backend; omitting them is a 422 (the bug US-13b
// fixes). expected_group_size is required by the backend only when
// group_type === 'group'.
export interface PortalSubmission {
  visitor_full_name: string
  contact_channel: 'email' | 'sms'
  contact_value: string
  host_hint: string | null
  purpose: string
  group_type: 'individual' | 'group'
  expected_group_size: number | null
  identity_verification_choice: 'upload_now' | 'send_to_host'
  privacy_notice_acknowledged: boolean
  privacy_notice_version: string
  turnstile_token: string
}

export interface PortalSubmissionAccepted {
  tracking_reference: string
}

// PortalTrackingStatus (US-13a). Deliberately only these three fields -- the
// server never returns a resolved employee name or a check-in code.
export interface PortalTrackingStatus {
  status: string
  visitor_full_name: string
  host_hint: string | null
}

// One error type for every non-OK response -- the UI renders a single generic
// message regardless of status (anti-enumeration; the server already decided).
export class PortalApiError extends Error {
  readonly httpStatus: number
  constructor(httpStatus: number) {
    super('portal_request_failed')
    this.name = 'PortalApiError'
    this.httpStatus = httpStatus
  }
}

export async function submitVisitRequest(
  tenantSlug: string,
  body: PortalSubmission,
): Promise<PortalSubmissionAccepted> {
  const response = await fetch(`${API_BASE_URL}/public/portal/${tenantSlug}/visit-requests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new PortalApiError(response.status)
  }
  return response.json()
}

export async function trackVisitRequest(
  tenantSlug: string,
  trackingReference: string,
): Promise<PortalTrackingStatus> {
  const response = await fetch(
    `${API_BASE_URL}/public/portal/${tenantSlug}/visit-requests/${encodeURIComponent(trackingReference)}`,
  )
  if (!response.ok) {
    throw new PortalApiError(response.status)
  }
  return response.json()
}
