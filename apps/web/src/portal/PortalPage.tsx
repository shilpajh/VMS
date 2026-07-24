import { useTranslation } from 'react-i18next'
import { LogIn } from 'lucide-react'
import { PortalRequestForm } from './PortalRequestForm'
import { TrackingLookup } from './TrackingLookup'

// Public portal landing page (US-13b): a plain responsive card grid --
// Request a visit / Track a visit / Log in -- matching the org prototype's
// structure without pixel-copying its illustrated two-panel styling (Gate-1
// decision 2). The OTP wizard the prototype shows is deferred until an
// SMS/email relay worker exists to deliver a code (US-13b Gate-1 decision 1).
interface PortalPageProps {
  tenantSlug: string
}

export function PortalPage({ tenantSlug }: PortalPageProps) {
  const { t } = useTranslation()

  return (
    <main className="min-h-screen bg-slate-50">
      <div className="max-w-5xl mx-auto p-4 sm:p-8">
        <header className="mb-6">
          <div className="flex items-center text-3xl font-bold mb-2">
            <span className="text-blue-600">{t('portal.brandPrefix', 'acm')}</span>
            <span className="bg-blue-600 text-white rounded-md px-1.5 ml-0.5">
              {t('portal.brandSuffix', 'e')}
            </span>
          </div>
          <h1 className="text-2xl font-semibold text-blue-700 leading-snug">
            {t('portal.welcomeTitle', 'Welcome to our Visitor Management System')}
          </h1>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <PortalRequestForm tenantSlug={tenantSlug} />
          <TrackingLookup tenantSlug={tenantSlug} />

          <section
            aria-label={t('portal.loginTitle', 'Log in to your account')}
            className="bg-white border border-slate-200/70 shadow-sm rounded-xl p-5 flex flex-col lg:col-span-2"
          >
            <h2 className="text-lg font-semibold text-blue-700 mb-2 flex items-center gap-2">
              <LogIn size={17} /> {t('portal.loginTitle', 'Log in to your account')}
            </h2>
            <p className="text-sm text-slate-500 mb-4">
              {t(
                'portal.loginBlurb',
                'Staff and hosts — sign in to manage visitors and visit requests.',
              )}
            </p>
            {/* Links to the app root, where App.tsx renders the staff MSAL
                sign-in shell (no auth code change in this story). */}
            <a
              href="/"
              className="inline-block w-full sm:w-auto text-center border border-blue-600 text-blue-700 text-sm font-semibold uppercase tracking-wide rounded-lg py-3 px-8 hover:bg-blue-50 mt-auto"
            >
              {t('portal.login', 'Log in')}
            </a>
          </section>
        </div>
      </div>
    </main>
  )
}
