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
    })
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
