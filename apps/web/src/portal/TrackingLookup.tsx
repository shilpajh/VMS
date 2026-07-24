import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Search } from 'lucide-react'
import { trackVisitRequest, type PortalTrackingStatus } from './portalApi'

const inputClasses =
  'mt-1 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500'

interface TrackingLookupProps {
  tenantSlug: string
}

// Track-a-visit card (US-13b). Renders ONLY the three fields US-13a's lookup
// returns (status, visitor_full_name, host_hint) -- never a resolved employee
// name or a check-in code (the server never sends them; this component also
// never reaches for them). One generic error for every non-OK response, same
// anti-enumeration discipline as the request form.
export function TrackingLookup({ tenantSlug }: TrackingLookupProps) {
  const { t } = useTranslation()
  const [reference, setReference] = useState('')

  const mutation = useMutation<PortalTrackingStatus, unknown, string>({
    mutationFn: (ref: string) => trackVisitRequest(tenantSlug, ref),
  })

  return (
    <section
      aria-label={t('portal.trackTitle', 'Track a visit request')}
      className="bg-white border border-slate-200/70 shadow-sm rounded-xl p-5 h-full flex flex-col"
    >
      <h2 className="text-lg font-semibold text-blue-700 mb-4 flex items-center gap-2">
        <Search size={17} /> {t('portal.trackTitle', 'Track a visit request')}
      </h2>

      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault()
          if (reference.trim()) mutation.mutate(reference.trim())
        }}
      >
        <label htmlFor="tracking-reference" className="text-xs text-slate-500 block">
          {t('portal.trackingId', 'Tracking ID')}
          <input
            id="tracking-reference"
            required
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            placeholder="REQ-000000000000"
            className={inputClasses}
          />
        </label>
        <button
          type="submit"
          disabled={mutation.isPending}
          className="w-full bg-blue-600 text-white text-sm font-semibold uppercase tracking-wide rounded-lg py-3 hover:bg-blue-700 disabled:opacity-50"
        >
          {t('portal.checkStatus', 'Check status')}
        </button>
      </form>

      {mutation.isSuccess && (
        <div role="status" className="mt-4 text-sm bg-slate-50 border border-slate-200 rounded-lg p-3 space-y-1">
          <p>
            <span className="text-slate-500">{t('portal.trackVisitor', 'Visitor')}: </span>
            <span className="font-medium">{mutation.data.visitor_full_name}</span>
          </p>
          {mutation.data.host_hint && (
            <p>
              <span className="text-slate-500">{t('portal.trackHost', 'Host')}: </span>
              {mutation.data.host_hint}
            </p>
          )}
          <p>
            <span className="text-slate-500">{t('portal.trackStatus', 'Status')}: </span>
            <span className="font-medium">{mutation.data.status}</span>
          </p>
        </div>
      )}

      {mutation.isError && (
        <p role="alert" className="mt-4 text-xs text-rose-600">
          {t('portal.trackError', 'No request found for that tracking ID, or it could not be checked.')}
        </p>
      )}
    </section>
  )
}
