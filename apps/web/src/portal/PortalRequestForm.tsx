import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { CheckCircle2 } from 'lucide-react'
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

const inputClasses =
  'mt-1 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500'
const labelClasses = 'text-xs text-slate-500 block'

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

  return (
    <div className="bg-white border border-slate-200/70 shadow-sm rounded-xl p-5 h-full flex flex-col">
      <h2 className="text-lg font-semibold text-blue-700 mb-4">
        {t('portal.formTitle', 'Request a visit')}
      </h2>

      {mutation.isSuccess ? (
        <div
          aria-label={t('portal.successLabel', 'Visit request submitted')}
          className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-center my-auto"
        >
          <CheckCircle2 size={24} className="mx-auto text-blue-600 mb-2" />
          <p className="text-sm text-blue-800 mb-1">
            {t('portal.successIntro', "Request submitted — your host has been notified.")}
          </p>
          <p className="text-xs text-slate-500 mb-2">
            {t('portal.trackingIdLabel', 'Your tracking ID:')}
          </p>
          <p className="text-lg font-semibold text-blue-900 font-mono">
            {mutation.data.tracking_reference}
          </p>
        </div>
      ) : (
        <form
          className="space-y-3 flex-1 flex flex-col"
          onSubmit={(event) => {
            event.preventDefault()
            mutation.mutate()
          }}
        >
          <label htmlFor="visitor-full-name" className={labelClasses}>
            {t('portal.fullName', 'Your full name')}
            <span className="text-rose-500">*</span>
            <input
              id="visitor-full-name"
              required
              value={visitorFullName}
              onChange={(event) => setVisitorFullName(event.target.value)}
              className={inputClasses}
            />
          </label>

          <fieldset>
            <legend className={labelClasses}>
              {t('portal.contactChannel', 'How should we contact you?')}
              <span className="text-rose-500">*</span>
            </legend>
            <div className="flex gap-x-6 gap-y-2 mt-2">
              <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                <input
                  type="radio"
                  name="contact-channel"
                  checked={contactChannel === 'email'}
                  onChange={() => setContactChannel('email')}
                  className="accent-blue-600 w-4 h-4"
                />
                {t('portal.email', 'Email')}
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                <input
                  type="radio"
                  name="contact-channel"
                  checked={contactChannel === 'sms'}
                  onChange={() => setContactChannel('sms')}
                  className="accent-blue-600 w-4 h-4"
                />
                {t('portal.sms', 'SMS')}
              </label>
            </div>
          </fieldset>

          <label htmlFor="contact-value" className={labelClasses}>
            {contactChannel === 'email'
              ? t('portal.emailAddress', 'Email address')
              : t('portal.phoneNumber', 'Phone number')}
            <span className="text-rose-500">*</span>
            <input
              id="contact-value"
              required
              value={contactValue}
              onChange={(event) => setContactValue(event.target.value)}
              className={inputClasses}
            />
          </label>

          <label htmlFor="host-hint" className={labelClasses}>
            {t('portal.hostHint', 'Who are you visiting? (name or email)')}
            <input
              id="host-hint"
              value={hostHint}
              onChange={(event) => setHostHint(event.target.value)}
              className={inputClasses}
            />
          </label>

          <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={privacyAcknowledged}
              onChange={(event) => setPrivacyAcknowledged(event.target.checked)}
              required
              className="accent-blue-600 w-4 h-4 mt-0.5"
            />
            {t(
              'portal.privacyAcknowledgment',
              'I acknowledge the privacy notice (version {{version}})',
              { version: PRIVACY_NOTICE_VERSION },
            )}
          </label>

          <TurnstileWidget onToken={setTurnstileToken} />

          {mutation.isError && (
            <p role="alert" className="text-xs text-rose-600">
              {t('portal.submitError', 'Something went wrong. Please try again.')}
            </p>
          )}

          <button
            type="submit"
            disabled={mutation.isPending || !turnstileToken}
            className="w-full bg-blue-600 text-white text-sm font-semibold uppercase tracking-wide rounded-lg py-3 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed mt-auto"
          >
            {t('portal.submit', 'Submit request')}
          </button>
        </form>
      )}
    </div>
  )
}
