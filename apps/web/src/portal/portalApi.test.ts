import { afterEach, describe, expect, it, vi } from 'vitest'
import { PortalApiError, submitVisitRequest, trackVisitRequest } from './portalApi'

const body = {
  visitor_full_name: 'Jane Visitor',
  contact_channel: 'email' as const,
  contact_value: 'jane@example.com',
  host_hint: 'Rahul',
  purpose: 'Business meeting',
  group_type: 'individual' as const,
  expected_group_size: null,
  identity_verification_choice: 'send_to_host' as const,
  privacy_notice_acknowledged: true,
  privacy_notice_version: 'v1',
  turnstile_token: 'tok',
}

describe('portalApi', () => {
  afterEach(() => vi.restoreAllMocks())

  it('POSTs the submission to the correct URL with the full contract body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ tracking_reference: 'REQ-1' }), { status: 202 }),
    )
    const result = await submitVisitRequest('acme-corp', body)
    expect(result.tracking_reference).toBe('REQ-1')
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toContain('/public/portal/acme-corp/visit-requests')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toMatchObject({
      purpose: 'Business meeting',
      group_type: 'individual',
      identity_verification_choice: 'send_to_host',
    })
  })

  it('throws PortalApiError with the http status on a non-OK submission', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 422 }))
    await expect(submitVisitRequest('acme-corp', body)).rejects.toBeInstanceOf(PortalApiError)
  })

  it('GETs the tracking lookup at the correct URL and returns the status', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ status: 'Requested', visitor_full_name: 'Jane', host_hint: 'Rahul' }),
        { status: 200 },
      ),
    )
    const result = await trackVisitRequest('acme-corp', 'REQ-123456789012')
    expect(result.status).toBe('Requested')
    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toContain('/public/portal/acme-corp/visit-requests/REQ-123456789012')
  })

  it('throws PortalApiError on a 404 tracking lookup', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 404 }))
    await expect(trackVisitRequest('acme-corp', 'REQ-000000000000')).rejects.toBeInstanceOf(
      PortalApiError,
    )
  })
})
