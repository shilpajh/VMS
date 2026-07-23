import { useTranslation } from 'react-i18next'
import { PortalRequestForm } from './PortalRequestForm'

// Two-panel shell matching the org's visitor-portal prototype (referenced
// by .claude/rules/frontend-react.md: "one consistent primary color/theme
// across all portals (blue per prototype)"). Only the "Request a visit"
// card is built here -- tracking-lookup/login/feedback/manual cards from
// the prototype are a separate, not-yet-scoped follow-up (US-11's plan
// explicitly fenced UI out of scope; this is a Quick Flow addition on top).
interface PortalPageProps {
  tenantSlug: string
}

export function PortalPage({ tenantSlug }: PortalPageProps) {
  const { t } = useTranslation()

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-5xl mx-auto p-4 sm:p-8">
        <div className="grid grid-cols-1 sm:grid-cols-[1fr_2fr] rounded-2xl overflow-hidden border border-slate-200">
          <div className="bg-blue-50/60 p-8 sm:p-10 flex flex-col">
            <div className="flex items-center text-3xl font-bold mb-6">
              <span className="text-blue-600">{t('portal.brandPrefix', 'acm')}</span>
              <span className="bg-blue-600 text-white rounded-md px-1.5 ml-0.5">
                {t('portal.brandSuffix', 'e')}
              </span>
            </div>
            <h1 className="text-2xl font-semibold text-blue-700 leading-snug max-w-xs">
              {t('portal.welcomeTitle', 'Welcome to our Visitor Management System')}
            </h1>
          </div>

          <div className="bg-white p-6 sm:p-10">
            <PortalRequestForm tenantSlug={tenantSlug} />
          </div>
        </div>
      </div>
    </div>
  )
}
