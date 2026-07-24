import { useTranslation } from 'react-i18next'
import { LogIn } from 'lucide-react'
import { PortalRequestForm } from './PortalRequestForm'
import { TrackingLookup } from './TrackingLookup'
import { PortalIllustration } from './PortalIllustration'

// Public portal landing page (US-13b). Two-panel layout matching the org
// prototype's look & feel -- a blue-tinted left panel (acme branding, welcome
// copy, reception illustration) beside the visitor-facing cards (Request a
// visit / Track a visit / Log in). Styling only: the working direct-submit
// form is kept; the prototype's OTP flow (no relay worker yet) and its
// Feedback/manual cards (no PRD grounding) remain deliberately out of scope.
interface PortalPageProps {
  tenantSlug: string
}

export function PortalPage({ tenantSlug }: PortalPageProps) {
  const { t } = useTranslation()

  return (
    <main className="min-h-screen bg-slate-50">
      <div className="max-w-6xl mx-auto p-4 sm:p-8">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_2fr] rounded-2xl overflow-hidden border border-slate-200 bg-white shadow-sm">
          {/* Left panel — branding + welcome + illustration */}
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
            <div className="mt-8 w-full max-w-[240px]">
              <PortalIllustration />
            </div>
          </div>

          {/* Right panel — the cards */}
          <div className="bg-white p-6 sm:p-10">
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <PortalRequestForm tenantSlug={tenantSlug} />
              <TrackingLookup tenantSlug={tenantSlug} />

              <section
                aria-label={t('portal.loginTitle', 'Log in to your account')}
                className="bg-white border border-slate-200/70 shadow-sm rounded-xl p-5 flex flex-col xl:col-span-2"
              >
                <h2 className="text-base font-semibold text-blue-700 mb-2 flex items-center gap-2">
                  <LogIn size={16} className="shrink-0" /> {t('portal.loginTitle', 'Log in to your account')}
                </h2>
                <p className="text-xs text-slate-500 mb-4">
                  {t(
                    'portal.loginBlurb',
                    'Staff and hosts — sign in to manage visitors and visit requests.',
                  )}
                </p>
                {/* Links to the app root, where App.tsx renders the staff MSAL
                    sign-in shell (no auth code change in this story). */}
                <a
                  href="/"
                  className="inline-block w-full sm:w-auto text-center bg-blue-600 text-white text-sm font-semibold uppercase tracking-wide rounded-lg py-3 px-8 hover:bg-blue-700 mt-auto"
                >
                  {t('portal.login', 'Log in')}
                </a>
              </section>
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}
