import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { TurnstileWidget } from './Turnstile'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

// The privacy-notice version this build's form was written against (US-11
// plan: a placeholder pending real compliance sign-off, not final policy).
const PRIVACY_NOTICE_VERSION = 'v1'

interface PortalSubmissionResponse {
  tracking_reference: string
}

interface PortalSubmissionError {
  status: number
}

async function submitPortalRequest(
  tenantSlug: string,
  body: {
    visitor_full_name: string
    contact_channel: 'email' | 'sms'
    contact_value: string
    host_hint: string
    privacy_notice_acknowledged: boolean
    privacy_notice_version: string
    turnstile_token: string
  },
): Promise<PortalSubmissionResponse> {
  const response = await fetch(`${API_BASE_URL}/public/portal/${tenantSlug}/visit-requests`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const error: PortalSubmissionError = { status: response.status }
    throw error
  }
  return response.json()
}

interface PortalRequestFormProps {
  tenantSlug: string
}

export function PortalRequestForm({ tenantSlug }: PortalRequestFormProps) {
  const { t } = useTranslation()
  const [visitorFullName, setVisitorFullName] = useState('')
  const [contactChannel, setContactChannel] = useState<'email' | 'sms'>('email')
  const [contactValue, setContactValue] = useState('')
  const [hostHint, setHostHint] = useState('')
  const [privacyAcknowledged, setPrivacyAcknowledged] = useState(false)
  const [turnstileToken, setTurnstileToken] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      submitPortalRequest(tenantSlug, {
        visitor_full_name: visitorFullName,
        contact_channel: contactChannel,
        contact_value: contactValue,
        host_hint: hostHint,
        privacy_notice_acknowledged: privacyAcknowledged,
        privacy_notice_version: PRIVACY_NOTICE_VERSION,
        turnstile_token: turnstileToken,
      }),
  })

  if (mutation.isSuccess) {
    return (
      <section aria-label={t('portal.successLabel', 'Visit request submitted')}>
        <h2>{t('portal.successTitle', 'Request submitted')}</h2>
        <p>
          {t(
            'portal.successBody',
            'Your tracking reference is {{ref}}. Keep it in case you need to check on your request.',
            { ref: mutation.data.tracking_reference },
          )}
        </p>
      </section>
    )
  }

  return (
    <section aria-label={t('portal.formLabel', 'Request a visit')}>
      <h2>{t('portal.formTitle', 'Request a visit')}</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          mutation.mutate()
        }}
      >
        <label htmlFor="visitor-full-name">{t('portal.fullName', 'Your full name')}</label>
        <input
          id="visitor-full-name"
          required
          value={visitorFullName}
          onChange={(event) => setVisitorFullName(event.target.value)}
        />

        <fieldset>
          <legend>{t('portal.contactChannel', 'How should we contact you?')}</legend>
          <label>
            <input
              type="radio"
              name="contact-channel"
              checked={contactChannel === 'email'}
              onChange={() => setContactChannel('email')}
            />
            {t('portal.email', 'Email')}
          </label>
          <label>
            <input
              type="radio"
              name="contact-channel"
              checked={contactChannel === 'sms'}
              onChange={() => setContactChannel('sms')}
            />
            {t('portal.sms', 'SMS')}
          </label>
        </fieldset>

        <label htmlFor="contact-value">
          {contactChannel === 'email'
            ? t('portal.emailAddress', 'Email address')
            : t('portal.phoneNumber', 'Phone number')}
        </label>
        <input
          id="contact-value"
          required
          value={contactValue}
          onChange={(event) => setContactValue(event.target.value)}
        />

        <label htmlFor="host-hint">{t('portal.hostHint', "Who are you visiting? (name or email)")}</label>
        <input
          id="host-hint"
          value={hostHint}
          onChange={(event) => setHostHint(event.target.value)}
        />

        <label>
          <input
            type="checkbox"
            checked={privacyAcknowledged}
            onChange={(event) => setPrivacyAcknowledged(event.target.checked)}
            required
          />
          {t(
            'portal.privacyAcknowledgment',
            'I acknowledge the privacy notice (version {{version}})',
            { version: PRIVACY_NOTICE_VERSION },
          )}
        </label>

        <TurnstileWidget onToken={setTurnstileToken} />

        {mutation.isError && (
          <p role="alert">{t('portal.submitError', 'Something went wrong. Please try again.')}</p>
        )}

        <button type="submit" disabled={mutation.isPending || !turnstileToken}>
          {t('portal.submit', 'Submit request')}
        </button>
      </form>
    </section>
  )
}
