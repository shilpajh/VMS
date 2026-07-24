import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useMsal } from '@azure/msal-react'
import { getAccessToken } from '../auth/getAccessToken'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

// Mirrors services/core-api/app/api/dtos/visits.py::VisitOut (the fields
// this page actually renders) -- this component only fetches and renders
// the server's response, it makes no check-in/approval decision itself
// (frontend-react.md: "the server decides, the UI renders").
interface CheckinResponse {
  status: string
  visitor_full_name: string
  tracking_reference: string
}

async function submitCheckin(accessToken: string, checkinCode: string): Promise<CheckinResponse> {
  const response = await fetch(`${API_BASE_URL}/visits/checkin`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ checkin_code: checkinCode }),
  })
  if (!response.ok) {
    // One generic error, regardless of status (404 invalid/expired code,
    // 403 lacks checkin_confirm) -- the UI never distinguishes rejection
    // causes; that decision already happened server-side (US-01 plan,
    // anti-enumeration).
    throw new Error('checkin_failed')
  }
  return response.json()
}

export function CheckinPage() {
  const { t } = useTranslation()
  const { instance, accounts } = useMsal()
  const account = accounts[0]
  const [checkinCode, setCheckinCode] = useState('')

  const mutation = useMutation({
    mutationFn: async () => {
      if (!account) {
        throw new Error('CheckinPage: no authenticated MSAL account')
      }
      const accessToken = await getAccessToken(instance, account)
      return submitCheckin(accessToken, checkinCode)
    },
  })

  return (
    // A <section>, not <main> -- this page is rendered nested inside App's
    // own <main> shell (App.tsx's AuthenticatedCheckinGate), and a page
    // should only ever have one <main> landmark (WCAG 2.1 AA).
    <section aria-label={t('checkin.title', 'Visitor check-in')}>
      <h2>{t('checkin.title', 'Visitor check-in')}</h2>

      {mutation.isSuccess ? (
        <div
          aria-label={t('checkin.successLabel', 'Visitor checked in')}
          role="status"
        >
          <p>
            {t('checkin.successMessage', '{{name}} is checked in.', {
              name: mutation.data.visitor_full_name,
            })}
          </p>
          <p>{mutation.data.tracking_reference}</p>
        </div>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            mutation.mutate()
          }}
        >
          <label htmlFor="checkin-code">
            {t('checkin.codeLabel', 'Check-in code')}
            <input
              id="checkin-code"
              required
              value={checkinCode}
              onChange={(event) => setCheckinCode(event.target.value)}
            />
          </label>
          <button type="submit" disabled={mutation.isPending}>
            {t('checkin.submit', 'Check in')}
          </button>
        </form>
      )}

      {mutation.isError && (
        <p role="alert">
          {t('checkin.error', 'Invalid or expired check-in code.')}
        </p>
      )}
    </section>
  )
}
