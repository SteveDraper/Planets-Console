import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { BffHttpError } from '../api/bffHttpError'
import { LAST_LOGIN_USERNAME_STORAGE_KEY } from '../lib/rememberedLoginUsername'
import { useSessionStore } from '../stores/session'
import { useCredentialRequiredLoginStore } from './reportCredentialSensitiveFailure'
import { useIdentityLifecycle } from './useIdentityLifecycle'
import { probeCredentials } from '../api/credentialsClient'

vi.mock('../api/credentialsClient', () => ({
  probeCredentials: vi.fn(),
}))

describe('useIdentityLifecycle', () => {
  const refreshUnfinishedSelectedGame = vi.fn()

  beforeEach(() => {
    useSessionStore.getState().clearSession()
    useCredentialRequiredLoginStore.getState().clearForceLoginModal()
    localStorage.clear()
    refreshUnfinishedSelectedGame.mockReset()
    vi.mocked(probeCredentials).mockReset()
  })

  it('opens login modal and clears session on turn-ensure 401', async () => {
    useSessionStore.getState().adoptLoginName('Alice')
    const { result, rerender } = renderHook(
      (props: { turnEnsureIsError: boolean; turnEnsureError: unknown }) =>
        useIdentityLifecycle({
          shellStoreHydrated: true,
          selectedGameId: null,
          isGameFinished: null,
          refreshUnfinishedSelectedGame,
          turnEnsureIsError: props.turnEnsureIsError,
          turnEnsureError: props.turnEnsureError,
        }),
      { initialProps: { turnEnsureIsError: false, turnEnsureError: null as unknown } }
    )

    await waitFor(() => expect(result.current.silentLoginStatus).toBe('skipped'))

    rerender({
      turnEnsureIsError: true,
      turnEnsureError: new BffHttpError(401, 'Login credentials are required.', 'POST /ensure'),
    })

    await waitFor(() => expect(result.current.forceLoginModalOpen).toBe(true))
    expect(useSessionStore.getState().name).toBeNull()
  })

  it('ignores non-401 turn-ensure errors', async () => {
    useSessionStore.getState().adoptLoginName('Alice')
    const { result, rerender } = renderHook(
      (props: { turnEnsureIsError: boolean; turnEnsureError: unknown }) =>
        useIdentityLifecycle({
          shellStoreHydrated: true,
          selectedGameId: null,
          isGameFinished: null,
          refreshUnfinishedSelectedGame,
          turnEnsureIsError: props.turnEnsureIsError,
          turnEnsureError: props.turnEnsureError,
        }),
      { initialProps: { turnEnsureIsError: false, turnEnsureError: null as unknown } }
    )

    await waitFor(() => expect(result.current.silentLoginStatus).toBe('skipped'))

    rerender({
      turnEnsureIsError: true,
      turnEnsureError: new Error('Load failed'),
    })

    await waitFor(() => expect(result.current.silentLoginStatus).toBe('skipped'))
    expect(result.current.forceLoginModalOpen).toBe(false)
    expect(useSessionStore.getState().name).toBe('Alice')
  })

  it('refreshes unfinished game after silent restore', async () => {
    localStorage.setItem(LAST_LOGIN_USERNAME_STORAGE_KEY, 'Alice')
    vi.mocked(probeCredentials).mockResolvedValue(true)

    const { result } = renderHook(() =>
      useIdentityLifecycle({
        shellStoreHydrated: true,
        selectedGameId: '99',
        isGameFinished: false,
        refreshUnfinishedSelectedGame,
        turnEnsureIsError: false,
        turnEnsureError: null,
      })
    )

    await waitFor(() => expect(result.current.silentLoginStatus).toBe('restored'))
    expect(refreshUnfinishedSelectedGame).toHaveBeenCalled()
  })
})
