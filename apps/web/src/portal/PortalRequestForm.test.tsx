import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PortalRequestForm } from './PortalRequestForm'
import '../i18n'

vi.mock('./Turnstile', () => ({
  TurnstileWidget: ({ onToken }: { onToken: (token: string) => void }) => (
    <button type="button" onClick={() => onToken('fake-turnstile-token')}>
      complete-turnstile-challenge
    </button>
  ),
}))

function renderForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <PortalRequestForm tenantSlug="acme-corp" />
    </QueryClientProvider>,
  )
}

describe('PortalRequestForm', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('submits the form and shows the tracking reference on success', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ tracking_reference: 'REQ-123456789012' }), { status: 202 }),
    )

    renderForm()

    await user.type(screen.getByLabelText(/your full name/i), 'Jane Visitor')
    await user.type(screen.getByLabelText(/email address/i), 'jane@example.com')
    await user.type(screen.getByLabelText(/who are you visiting/i), 'rahul@acme')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: /complete-turnstile-challenge/i }))
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    await waitFor(() => expect(screen.getByText(/REQ-123456789012/)).toBeInTheDocument())

    const [, requestInit] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    const body = JSON.parse(requestInit.body as string)
    expect(body).toMatchObject({
      visitor_full_name: 'Jane Visitor',
      contact_channel: 'email',
      contact_value: 'jane@example.com',
      host_hint: 'rahul@acme',
      privacy_notice_acknowledged: true,
      turnstile_token: 'fake-turnstile-token',
      // US-13a now REQUIRES these three (default individual submission) --
      // omitting them was the 422 bug US-13b fixes.
      purpose: expect.any(String),
      group_type: 'individual',
      identity_verification_choice: expect.any(String),
    })
    expect(body.purpose.length).toBeGreaterThan(0)
  })

  it('requires a group size before submitting when group type is "group"', async () => {
    const user = userEvent.setup()
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ tracking_reference: 'REQ-1' }), { status: 202 }),
    )

    renderForm()

    await user.type(screen.getByLabelText(/your full name/i), 'Jane Visitor')
    await user.type(screen.getByLabelText(/email address/i), 'jane@example.com')
    await user.click(screen.getByLabelText(/group visitors/i))
    await user.click(screen.getByRole('checkbox', { name: /privacy notice/i }))
    await user.click(screen.getByRole('button', { name: /complete-turnstile-challenge/i }))
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    // Blocked: no fetch, and the group-size required error is shown.
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(screen.getByText(/enter your group size/i)).toBeInTheDocument()

    // Provide a size -> now it submits with expected_group_size.
    await user.type(screen.getByLabelText(/group size/i), '3')
    await user.click(screen.getByRole('button', { name: /submit request/i }))
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    const body = JSON.parse(
      (fetchSpy.mock.calls[0][1] as RequestInit).body as string,
    )
    expect(body).toMatchObject({ group_type: 'group', expected_group_size: 3 })
  })

  it('disables submit until the Turnstile challenge is completed', async () => {
    renderForm()
    expect(screen.getByRole('button', { name: /submit request/i })).toBeDisabled()
  })

  it('shows a distinct error state on a failed submission', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 429 }))

    renderForm()

    await user.type(screen.getByLabelText(/your full name/i), 'Jane Visitor')
    await user.type(screen.getByLabelText(/email address/i), 'jane@example.com')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: /complete-turnstile-challenge/i }))
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})
