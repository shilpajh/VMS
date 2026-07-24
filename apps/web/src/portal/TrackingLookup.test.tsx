import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TrackingLookup } from './TrackingLookup'
import '../i18n'

function renderCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <TrackingLookup tenantSlug="acme-corp" />
    </QueryClientProvider>,
  )
}

describe('TrackingLookup', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders the server status and the visitor\'s own submitted details', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ status: 'Registered', visitor_full_name: 'Jane Visitor', host_hint: 'Rahul' }),
        { status: 200 },
      ),
    )

    renderCard()
    await user.type(screen.getByLabelText(/tracking/i), 'REQ-123456789012')
    await user.click(screen.getByRole('button', { name: /check status/i }))

    await waitFor(() => expect(screen.getByText(/Registered/)).toBeInTheDocument())
    expect(screen.getByText(/Jane Visitor/)).toBeInTheDocument()
    expect(screen.getByText(/Rahul/)).toBeInTheDocument()
  })

  it('never renders a resolved employee name or a check-in code (only the 3 server fields)', async () => {
    const user = userEvent.setup()
    // Even if a (hypothetical) server leaked extra fields, the card must only
    // consume the three contract fields -- assert nothing else is rendered.
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          status: 'Registered',
          visitor_full_name: 'Jane Visitor',
          host_hint: 'Rahul',
          host_display_name: 'Rahul Mehta (SHOULD NOT RENDER)',
          checkin_code: 'SECRET-SHOULD-NOT-RENDER',
        }),
        { status: 200 },
      ),
    )

    renderCard()
    await user.type(screen.getByLabelText(/tracking/i), 'REQ-123456789012')
    await user.click(screen.getByRole('button', { name: /check status/i }))

    await waitFor(() => expect(screen.getByText(/Registered/)).toBeInTheDocument())
    expect(screen.queryByText(/Rahul Mehta/)).not.toBeInTheDocument()
    expect(screen.queryByText(/SECRET-SHOULD-NOT-RENDER/)).not.toBeInTheDocument()
  })

  it('renders one generic message on a 404 (unknown reference), never a status-specific one', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 404 }))

    renderCard()
    await user.type(screen.getByLabelText(/tracking/i), 'REQ-000000000000')
    await user.click(screen.getByRole('button', { name: /check status/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})
