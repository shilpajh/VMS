import { afterEach, describe, expect, it, vi } from 'vitest'
import { msalConfig, msalInstance } from './msal'

// Verifier for ADR-001 §5: staff SSO tokens are held in memory only, never
// localStorage or sessionStorage. These assertions are the concrete check
// for that decision, not just a comment in the config file.
describe('msal config (ADR-001 §5: in-memory token storage only)', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('explicitly requests memory-only cache, never localStorage/sessionStorage', () => {
    expect(msalConfig.cache?.cacheLocation).toBe('memoryStorage')
    expect(msalConfig.cache?.cacheLocation).not.toBe('localStorage')
    expect(msalConfig.cache?.cacheLocation).not.toBe('sessionStorage')
  })

  it('never writes to localStorage or sessionStorage when the configured instance is used', () => {
    // Storage.prototype.setItem is shared by both window.localStorage and
    // window.sessionStorage, so a single spy covers both.
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')

    // Exercise the configured singleton the way the app's login flow does
    // (reading current accounts before deciding to show sign-in vs session
    // UI) without needing network/popup interaction.
    msalInstance.getAllAccounts()

    expect(setItemSpy).not.toHaveBeenCalled()
    // Note: this only exercises the account-read path (no network call is
    // made in these tests, since there is no real Entra app registration in
    // this environment). MSAL's own internal bookkeeping for things like
    // popup/redirect correlation IDs is not exercised here; no such calls
    // were observed touching Storage.prototype.setItem during this test in
    // the current @azure/msal-browser version, but a full interactive login
    // flow against a real Entra tenant is out of scope for this unit test.
    setItemSpy.mockRestore()
  })

  it('uses a placeholder client ID/authority when no real Entra values are configured', () => {
    // Guards against accidentally fabricating a real-looking tenant ID as a
    // "default" — the placeholder must be obviously fake.
    expect(msalConfig.auth.clientId).toBe('00000000-0000-0000-0000-000000000000')
    expect(msalConfig.auth.authority).toContain('placeholder-tenant-id')
  })
})
