import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { useMsal } from '@azure/msal-react'
import { getAccessToken } from './getAccessToken'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

// Mirrors services/core-api/app/api/dtos/identity.py::MeResponse exactly.
// This hook only fetches and normalizes that response — it does not compute
// or hardcode any role/permission-based UI decision itself.
export interface CurrentUser {
  id: string
  tenant_id: string
  display_name: string
  roles: string[]
  permissions: string[]
}

async function fetchCurrentUser(token: string): Promise<CurrentUser> {
  const response = await fetch(`${API_BASE_URL}/me`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    throw new Error(`GET /me failed: ${response.status}`)
  }
  return response.json()
}

/**
 * Fetches the current authenticated staff user's profile from GET /me,
 * attaching a bearer token acquired via MSAL (in-memory cache only, per
 * ADR-001 §5). Enabled only once an MSAL account is present.
 */
export function useCurrentUser(): UseQueryResult<CurrentUser, Error> {
  const { instance, accounts } = useMsal()
  const account = accounts[0]

  return useQuery({
    queryKey: ['currentUser', account?.homeAccountId],
    queryFn: async () => {
      if (!account) {
        throw new Error('useCurrentUser: no authenticated MSAL account')
      }
      const accessToken = await getAccessToken(instance, account)
      return fetchCurrentUser(accessToken)
    },
    enabled: Boolean(account),
  })
}
