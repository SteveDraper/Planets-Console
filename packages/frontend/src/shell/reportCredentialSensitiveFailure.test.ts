import { describe, it, expect, beforeEach } from 'vitest'
import { BffHttpError } from '../api/bffHttpError'
import { useSessionStore } from '../stores/session'
import {
  reportCredentialSensitiveFailure,
  useCredentialRequiredLoginStore,
} from './reportCredentialSensitiveFailure'

describe('reportCredentialSensitiveFailure', () => {
  beforeEach(() => {
    useSessionStore.getState().clearSession()
    useCredentialRequiredLoginStore.getState().clearForceLoginModal()
  })

  it('clears session and requests login modal on 401', () => {
    useSessionStore.getState().adoptLoginName('Alice')

    const handled = reportCredentialSensitiveFailure(
      new BffHttpError(401, 'Login credentials are required.', 'POST /load-all')
    )

    expect(handled).toBe(true)
    expect(useSessionStore.getState().name).toBeNull()
    expect(useCredentialRequiredLoginStore.getState().forceLoginModal).toBe(true)
  })

  it('ignores non-401 errors', () => {
    useSessionStore.getState().adoptLoginName('Alice')

    const handled = reportCredentialSensitiveFailure(new Error('Load failed'))

    expect(handled).toBe(false)
    expect(useSessionStore.getState().name).toBe('Alice')
    expect(useCredentialRequiredLoginStore.getState().forceLoginModal).toBe(false)
  })
})
