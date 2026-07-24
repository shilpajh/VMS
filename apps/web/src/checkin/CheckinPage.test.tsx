import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CheckinPage } from './CheckinPage'
import '../i18n'

const mockUseMsal = vi.fn()

vi.mock('@azure/msal-react', () => ({
  useMsal: () => mockUseMsal(),
}))

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <CheckinPage />
    </QueryClientProvider>,
  )
}

describe('CheckinPage', () => {
  beforeEach(() => {
    mockUseMsal.mockReturnValue({
      instance: {
        acquireTokenSilent: vi.fn().mockResolvedValue({ accessToken: 'fake-token' }),
        acquireTokenPopup: vi.fn(),
      },
      accounts: [{ homeAccountId: 'acc-reception' }],
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('submits the entered code and renders the checked-in result on success', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          status: 'CheckedIn',
          visitor_full_name: 'Jane Visitor',
          tracking_reference: 'REQ-123456789012',
        }),
        { status: 200 },
      ),
    )

    renderPage()

    await user.type(screen.getByLabelText(/check-in code/i), 'a-valid-code')
    await user.click(screen.getByRole('button', { name: /check in/i }))

    await waitFor(() => expect(screen.getByText(/Jane Visitor/)).toBeInTheDocument())

    const [url, requestInit] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toContain('/visits/checkin')
    expect(requestInit.headers.Authorization).toBe('Bearer fake-token')
    expect(JSON.parse(requestInit.body as string)).toEqual({ checkin_code: 'a-valid-code' })
  })

  it('renders a single generic error message on a 404 (invalid or expired code) -- never a distinguishable one', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'invalid or expired check-in code' }), { status: 404 }),
    )

    renderPage()

    await user.type(screen.getByLabelText(/check-in code/i), 'expired-or-unknown')
    await user.click(screen.getByRole('button', { name: /check in/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  it('renders the same generic error message on a 403 -- no client-side policy decision', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 403 }))

    renderPage()

    await user.type(screen.getByLabelText(/check-in code/i), 'some-code')
    await user.click(screen.getByRole('button', { name: /check in/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  it('moves focus to the success message once the form unmounts (WCAG 2.4.3)', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          status: 'CheckedIn',
          visitor_full_name: 'Jane Visitor',
          tracking_reference: 'REQ-123456789012',
        }),
        { status: 200 },
      ),
    )

    renderPage()

    await user.type(screen.getByLabelText(/check-in code/i), 'a-valid-code')
    await user.click(screen.getByRole('button', { name: /check in/i }))

    await waitFor(() => expect(screen.getByRole('status')).toHaveFocus())
  })

  it('marks the code input invalid and describes it by the error message on failure', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 404 }))

    renderPage()

    const input = screen.getByLabelText(/check-in code/i)
    await user.type(input, 'unknown-code')
    await user.click(screen.getByRole('button', { name: /check in/i }))

    const alert = await screen.findByRole('alert')
    await waitFor(() => expect(input).toHaveAttribute('aria-invalid', 'true'))
    expect(input.getAttribute('aria-describedby')).toBe(alert.id)
  })

  it('submits via keyboard alone (Enter in the code field), with no mouse interaction', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          status: 'CheckedIn',
          visitor_full_name: 'Jane Visitor',
          tracking_reference: 'REQ-123456789012',
        }),
        { status: 200 },
      ),
    )

    renderPage()

    await user.type(screen.getByLabelText(/check-in code/i), 'a-valid-code{Enter}')

    await waitFor(() => expect(screen.getByText(/Jane Visitor/)).toBeInTheDocument())
  })
})
