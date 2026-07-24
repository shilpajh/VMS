import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PortalRequestForm } from './PortalRequestForm'
import '../i18n'

// US-13b DoD (docs/plans/US-13b.md, Part C): "WCAG 2.1 AA: ... focus-to-result
// on submit ... tested" -- explicitly "the standard US-01's CheckinPage met".
// CheckinPage.tsx moves visible keyboard focus onto its role="status" success
// region via a ref + tabIndex={-1} + useEffect(...).focus() (see
// CheckinPage.test.tsx:108, `expect(screen.getByRole('status')).toHaveFocus()`),
// because the form unmounts on success and focus would otherwise silently
// revert to <body> (WCAG 2.4.3 Focus Order) -- a live region's aria
// announcement alone does not satisfy this for sighted keyboard users.
//
// PortalRequestForm's success div (lines 82-98) has the same unmount shape
// (form -> replaced by a role="status" div) but no ref/tabIndex/focus() call.
// This test encodes the DoD line as a verifier; it is expected to FAIL
// against the current implementation until PortalRequestForm adopts the same
// pattern as CheckinPage.
vi.mock('./Turnstile', () => ({
  TurnstileWidget: ({ onToken }: { onToken: (token: string) => void }) => (
    <button type="button" onClick={() => onToken('fake-turnstile-token')}>
      complete-turnstile-challenge
    </button>
  ),
}))

describe('PortalRequestForm accessibility: focus-to-result on submit', () => {
  afterEach(() => vi.restoreAllMocks())

  it('moves keyboard focus to the success status region once the form unmounts', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ tracking_reference: 'REQ-123456789012' }), { status: 202 }),
    )

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <PortalRequestForm tenantSlug="acme-corp" />
      </QueryClientProvider>,
    )

    await user.type(screen.getByLabelText(/your full name/i), 'Jane Visitor')
    await user.type(screen.getByLabelText(/email address/i), 'jane@example.com')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: /complete-turnstile-challenge/i }))
    await user.click(screen.getByRole('button', { name: /submit request/i }))

    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument())
    // WCAG 2.4.3 Focus Order: since the form (incl. the submit button) has
    // unmounted, focus must land on the replacement content -- not silently
    // revert to <body>.
    expect(screen.getByRole('status')).toHaveFocus()
  })
})
