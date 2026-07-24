import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { PortalPage } from './PortalPage'
import '../i18n'

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <PortalPage tenantSlug="acme-corp" />
    </QueryClientProvider>,
  )
}

describe('PortalPage', () => {
  it('renders the three cards: Request a visit, Track a visit, Log in', () => {
    renderPage()
    expect(screen.getByRole('heading', { name: /request a visit/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /track a visit/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /log in/i })).toBeInTheDocument()
  })

  it('the Log in card links to the staff shell (app root)', () => {
    renderPage()
    const loginLink = screen.getByRole('link', { name: /log in/i })
    expect(loginLink).toHaveAttribute('href', '/')
  })
})
