import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import './i18n'

const mockUseIsAuthenticated = vi.fn()
const mockUseMsal = vi.fn()

vi.mock('@azure/msal-react', () => ({
  useIsAuthenticated: () => mockUseIsAuthenticated(),
  useMsal: () => mockUseMsal(),
}))

function renderApp() {
  // retry: false — otherwise TanStack Query's default retry/backoff keeps
  // the 401 test in a loading state past the assertion's wait window.
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

function mockHealthAndMeFetch(meResponse: Response) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.endsWith('/health')) {
      return Promise.resolve(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }))
    }
    return Promise.resolve(meResponse)
  })
}

function mockAuthenticatedMsal(homeAccountId: string) {
  mockUseIsAuthenticated.mockReturnValue(true)
  mockUseMsal.mockReturnValue({
    instance: {
      loginPopup: vi.fn(),
      acquireTokenSilent: vi.fn().mockResolvedValue({ accessToken: 'fake-token' }),
      acquireTokenPopup: vi.fn(),
    },
    accounts: [{ homeAccountId }],
  })
}

describe('App', () => {
  beforeEach(() => {
    mockUseIsAuthenticated.mockReturnValue(false)
    mockUseMsal.mockReturnValue({
      instance: { loginPopup: vi.fn(), acquireTokenSilent: vi.fn(), acquireTokenPopup: vi.fn() },
      accounts: [],
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the core-api health status once the fetch resolves', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
    )

    renderApp()

    await waitFor(() => expect(screen.getByText(/core-api status: ok/i)).toBeInTheDocument())
  })

  it('shows a sign-in affordance before staff login', () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
    )

    renderApp()

    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('renders display name and roles once GET /me succeeds with roles assigned', async () => {
    mockAuthenticatedMsal('acc-with-roles')
    mockHealthAndMeFetch(
      new Response(
        JSON.stringify({
          id: 'user-1',
          tenant_id: 'tenant-1',
          display_name: 'Priya Sharma',
          roles: ['reception_security'],
          permissions: ['approve_deny_holds'],
        }),
        { status: 200 },
      ),
    )

    renderApp()

    await waitFor(() => expect(screen.getByText(/Priya Sharma/)).toBeInTheDocument())
    expect(screen.getByText('reception_security')).toBeInTheDocument()
    expect(screen.queryByText(/no roles assigned yet/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('renders a distinct "no roles assigned yet" message when GET /me returns zero roles (JIT UX cliff)', async () => {
    mockAuthenticatedMsal('acc-zero-roles')
    mockHealthAndMeFetch(
      new Response(
        JSON.stringify({
          id: 'user-2',
          tenant_id: 'tenant-1',
          display_name: 'New Hire',
          roles: [],
          permissions: [],
        }),
        { status: 200 },
      ),
    )

    renderApp()

    await waitFor(() => expect(screen.getByText(/no roles assigned yet/i)).toBeInTheDocument())
    // Must be distinct from an error state, not merely worded differently.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('renders a distinct error state when GET /me returns 401', async () => {
    mockAuthenticatedMsal('acc-unauthorized')
    mockHealthAndMeFetch(new Response(null, { status: 401 }))

    renderApp()

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.queryByText(/no roles assigned yet/i)).not.toBeInTheDocument()
  })

  describe('/checkin routing gate (US-01)', () => {
    afterEach(() => {
      window.history.pushState({}, '', '/')
    })

    it('renders CheckinPage at /checkin when the caller has checkin_confirm', async () => {
      window.history.pushState({}, '', '/checkin')
      mockAuthenticatedMsal('acc-reception')
      mockHealthAndMeFetch(
        new Response(
          JSON.stringify({
            id: 'user-3',
            tenant_id: 'tenant-1',
            display_name: 'Reception Staff',
            roles: ['reception_security'],
            permissions: ['checkin_confirm'],
          }),
          { status: 200 },
        ),
      )

      renderApp()

      await waitFor(() => expect(screen.getByLabelText(/check-in code/i)).toBeInTheDocument())
    })

    it('falls through to StaffSession at /checkin when the caller lacks checkin_confirm', async () => {
      window.history.pushState({}, '', '/checkin')
      mockAuthenticatedMsal('acc-host-only')
      mockHealthAndMeFetch(
        new Response(
          JSON.stringify({
            id: 'user-4',
            tenant_id: 'tenant-1',
            display_name: 'Host Only',
            roles: ['host'],
            permissions: ['approve_deny_visits'],
          }),
          { status: 200 },
        ),
      )

      renderApp()

      await waitFor(() => expect(screen.getByText(/Host Only/)).toBeInTheDocument())
      expect(screen.queryByLabelText(/check-in code/i)).not.toBeInTheDocument()
    })
  })
})
