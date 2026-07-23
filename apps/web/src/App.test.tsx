import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import './i18n'

describe('App', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the core-api health status once the fetch resolves', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
    )
    const queryClient = new QueryClient()

    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(screen.getByText(/core-api status: ok/i)).toBeInTheDocument())
  })
})
