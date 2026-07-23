import { PublicClientApplication, type Configuration } from '@azure/msal-browser'

// Placeholder Entra ID app registration values. There is no real Entra app
// registration available in this environment; these MUST be overridden via
// real environment variables (VITE_ENTRA_CLIENT_ID / VITE_ENTRA_TENANT_ID)
// in every real deployment. The defaults below are deliberately obviously
// fake so a missing .env is loud, not silently "working".
const PLACEHOLDER_CLIENT_ID = '00000000-0000-0000-0000-000000000000'
const PLACEHOLDER_TENANT_ID = 'placeholder-tenant-id'

const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID ?? PLACEHOLDER_CLIENT_ID
const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID ?? PLACEHOLDER_TENANT_ID

export const msalConfig: Configuration = {
  auth: {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri: import.meta.env.VITE_ENTRA_REDIRECT_URI ?? window.location.origin,
  },
  cache: {
    // ADR-001 §5: tokens are held in memory only, never localStorage or
    // sessionStorage. "memoryStorage" is explicit here (rather than relying
    // on an omitted default) so this decision is visible and testable.
    cacheLocation: 'memoryStorage',
  },
}

export const loginRequest = {
  // Minimal scope set for this story: enough to call core-api's /me.
  scopes: [`api://${clientId}/access_as_user`],
}

export const msalInstance = new PublicClientApplication(msalConfig)
