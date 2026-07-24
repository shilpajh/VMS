import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useIsAuthenticated, useMsal } from '@azure/msal-react'
import { loginRequest } from './auth/msal'
import { useCurrentUser } from './auth/useCurrentUser'
import { PortalPage } from './portal/PortalPage'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

interface HealthResponse {
  status: string
}

async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`)
  if (!response.ok) {
    throw new Error(`health check failed: ${response.status}`)
  }
  return response.json()
}

// Before login: a sign-in affordance. The UI never decides who is allowed to
// sign in or what they can do once in — it only triggers the MSAL flow.
function StaffSignIn() {
  const { t } = useTranslation()
  const { instance } = useMsal()

  const handleSignIn = () => {
    void instance.loginPopup(loginRequest)
  }

  return (
    <button type="button" onClick={handleSignIn}>
      {t('auth.signIn', 'Sign in with your organization account')}
    </button>
  )
}

// After login: renders GET /me's normalized response as-is. No role/policy
// decision is made here — the server has already decided; this only renders
// three distinct states (loading / no-roles-yet / error) plus the happy path.
function StaffSession() {
  const { t } = useTranslation()
  const { data, error, isLoading } = useCurrentUser()

  if (isLoading) {
    return <p>{t('auth.loading', 'Loading your profile…')}</p>
  }

  if (error) {
    return (
      <p role="alert">
        {t('auth.error', 'Could not load your profile. Please try again or contact support.')}
      </p>
    )
  }

  if (data && data.roles.length === 0) {
    // JIT-zero-roles UX cliff (US-10 plan, Part A Risks): a brand-new SSO
    // user with no role assigned yet must look distinct from an error, not
    // like something is broken.
    return (
      <p role="status">
        {t('auth.noRoles', 'No roles assigned yet — contact your administrator.')}
      </p>
    )
  }

  if (data) {
    return (
      <div>
        <p>{t('auth.displayName', 'Signed in as {{name}}', { name: data.display_name })}</p>
        <ul aria-label={t('auth.rolesLabel', 'Your roles')}>
          {data.roles.map((role) => (
            <li key={role}>{role}</li>
          ))}
        </ul>
      </div>
    )
  }

  return null
}

// The public portal path (/portal/{tenant_slug}) is unauthenticated and
// deliberately bypasses the staff sign-in / health-check shell entirely --
// it's the surface a visitor with no Smart VMS account ever sees.
function usePortalTenantSlug(): string | null {
  const match = /^\/portal\/([^/]+)\/?$/.exec(window.location.pathname)
  return match ? match[1] : null
}

function App() {
  const { t } = useTranslation()
  const isAuthenticated = useIsAuthenticated()
  const portalTenantSlug = usePortalTenantSlug()
  const { data, error, isLoading } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    enabled: !portalTenantSlug,
  })

  if (portalTenantSlug) {
    return <PortalPage tenantSlug={portalTenantSlug} />
  }

  return (
    <main>
      <h1>{t('app.title', 'Smart VMS')}</h1>
      {isLoading && <p>{t('health.checking', 'Checking core-api…')}</p>}
      {error && <p role="alert">{t('health.error', 'core-api unreachable')}</p>}
      {data && <p>{t('health.status', 'core-api status: {{status}}', { status: data.status })}</p>}

      <section aria-label={t('auth.sectionLabel', 'Staff sign-in')}>
        {isAuthenticated ? <StaffSession /> : <StaffSignIn />}
      </section>
    </main>
  )
}

export default App
