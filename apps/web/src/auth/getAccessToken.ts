import type { AccountInfo, IPublicClientApplication } from '@azure/msal-browser'
import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { loginRequest } from './msal'

/**
 * Shared silent-then-popup token acquisition, extracted from
 * useCurrentUser's original inline logic so CheckinPage (US-01) doesn't
 * duplicate this non-trivial auth flow at a second call site.
 */
export async function getAccessToken(
  instance: IPublicClientApplication,
  account: AccountInfo,
): Promise<string> {
  try {
    const result = await instance.acquireTokenSilent({ ...loginRequest, account })
    return result.accessToken
  } catch (silentError) {
    if (silentError instanceof InteractionRequiredAuthError) {
      const result = await instance.acquireTokenPopup({ ...loginRequest, account })
      return result.accessToken
    }
    throw silentError
  }
}
