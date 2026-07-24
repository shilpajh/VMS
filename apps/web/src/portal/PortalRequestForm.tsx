import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { CheckCircle2 } from 'lucide-react'
import { TurnstileWidget } from './Turnstile'
import { submitVisitRequest } from './portalApi'

// The privacy-notice version this build's form was written against (US-11
// plan: a placeholder pending real compliance sign-off, not final policy).
const PRIVACY_NOTICE_VERSION = 'v1'

// Visit purposes offered to the visitor. `purpose` is a required free-string
// on US-13a's DTO; a fixed select keeps submissions clean and the field
// non-empty. (Mirrors the prototype's purpose list.)
const PURPOSES = [
  'Business meeting',
  'Interview',
  'Contractor work',
  'Delivery',
  'Vendor visit',
] as const

type GroupType = 'individual' | 'group'
type IdentityChoice = 'upload_now' | 'send_to_host'

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
  const [purpose, setPurpose] = useState<string>(PURPOSES[0])
  const [groupType, setGroupType] = useState<GroupType>('individual')
  const [groupSize, setGroupSize] = useState('')
  const [identityChoice, setIdentityChoice] = useState<IdentityChoice>('send_to_host')
  const [privacyAcknowledged, setPrivacyAcknowledged] = useState(false)
  const [turnstileToken, setTurnstileToken] = useState('')
  // Client-side mirror of US-13a's DTO validator (group -> size required), so
  // a group submission never round-trips to a guaranteed 422.
  const [groupSizeError, setGroupSizeError] = useState(false)
  const successRef = useRef<HTMLDivElement>(null)

  const mutation = useMutation({
    mutationFn: () =>
      submitVisitRequest(tenantSlug, {
        visitor_full_name: visitorFullName,
        contact_channel: contactChannel,
        contact_value: contactValue,
        host_hint: hostHint || null,
        purpose,
        group_type: groupType,
        expected_group_size: groupType === 'group' ? Number(groupSize) : null,
        identity_verification_choice: identityChoice,
        privacy_notice_acknowledged: privacyAcknowledged,
        privacy_notice_version: PRIVACY_NOTICE_VERSION,
        turnstile_token: turnstileToken,
      }),
  })

  // Move visible keyboard focus to the success message once it replaces the
  // form (the submit button unmounts, so focus would otherwise revert to
  // <body>) -- WCAG 2.4.3, the same fix CheckinPage carries (US-13b verify
  // Should-fix; the DoD committed to matching CheckinPage's focus handling).
  useEffect(() => {
    if (mutation.isSuccess) successRef.current?.focus()
  }, [mutation.isSuccess])

  const handleSubmit = () => {
    // Mirror US-13a's DTO validator: group requires a size >= 1 (an empty
    // value OR a non-positive number both block, so the client fully matches
    // the backend's `ge=1`, not just "non-empty" -- US-13b verify Note).
    if (groupType === 'group' && Number(groupSize) < 1) {
      setGroupSizeError(true)
      return
    }
    setGroupSizeError(false)
    mutation.mutate()
  }

  return (
    <div className="bg-white border border-slate-200/70 shadow-sm rounded-xl p-5 h-full flex flex-col">
      <h2 className="text-lg font-semibold text-blue-700 mb-4">
        {t('portal.formTitle', 'Request a visit')}
      </h2>

      {mutation.isSuccess ? (
        <div
          ref={successRef}
          tabIndex={-1}
          role="status"
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
            handleSubmit()
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

          <label htmlFor="purpose" className={labelClasses}>
            {t('portal.purpose', 'Purpose of visit')}
            <span className="text-rose-500">*</span>
            <select
              id="purpose"
              value={purpose}
              onChange={(event) => setPurpose(event.target.value)}
              className={inputClasses}
            >
              {PURPOSES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>

          <fieldset>
            <legend className={labelClasses}>
              {t('portal.groupType', 'Are you visiting alone or as a group?')}
              <span className="text-rose-500">*</span>
            </legend>
            <div className="flex gap-x-6 gap-y-2 mt-2">
              <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                <input
                  type="radio"
                  name="group-type"
                  checked={groupType === 'individual'}
                  onChange={() => {
                    setGroupType('individual')
                    setGroupSizeError(false)
                  }}
                  className="accent-blue-600 w-4 h-4"
                />
                {t('portal.individual', 'Individual')}
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                <input
                  type="radio"
                  name="group-type"
                  checked={groupType === 'group'}
                  onChange={() => setGroupType('group')}
                  className="accent-blue-600 w-4 h-4"
                />
                {t('portal.groupVisitors', 'Group visitors')}
              </label>
            </div>
          </fieldset>

          {groupType === 'group' && (
            <label htmlFor="group-size" className={labelClasses}>
              {t('portal.groupSize', 'Group size')}
              <span className="text-rose-500">*</span>
              <input
                id="group-size"
                type="number"
                min={1}
                value={groupSize}
                onChange={(event) => {
                  setGroupSize(event.target.value)
                  if (event.target.value.trim()) setGroupSizeError(false)
                }}
                aria-invalid={groupSizeError}
                aria-describedby={groupSizeError ? 'group-size-error' : undefined}
                className={inputClasses}
              />
              {groupSizeError && (
                <span id="group-size-error" role="alert" className="text-xs text-rose-600">
                  {t('portal.groupSizeRequired', 'Please enter your group size.')}
                </span>
              )}
            </label>
          )}

          <fieldset>
            <legend className={labelClasses}>
              {t('portal.identityChoice', 'Identity verification')}
              <span className="text-rose-500">*</span>
            </legend>
            <div className="flex flex-col gap-2 mt-2">
              <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
                <input
                  type="radio"
                  name="identity-choice"
                  checked={identityChoice === 'send_to_host'}
                  onChange={() => setIdentityChoice('send_to_host')}
                  className="accent-blue-600 w-4 h-4 mt-0.5"
                />
                {t('portal.sendToHost', "I'll send my ID to my host directly")}
              </label>
              <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
                <input
                  type="radio"
                  name="identity-choice"
                  checked={identityChoice === 'upload_now'}
                  onChange={() => setIdentityChoice('upload_now')}
                  className="accent-blue-600 w-4 h-4 mt-0.5"
                />
                {t('portal.uploadNow', 'I will upload my ID at the kiosk on arrival')}
              </label>
            </div>
          </fieldset>

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
