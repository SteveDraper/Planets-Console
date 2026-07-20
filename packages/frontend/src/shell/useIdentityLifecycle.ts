import { useCallback, useEffect, useRef } from 'react'
import {
  reportCredentialSensitiveFailure,
  useCredentialRequiredLoginStore,
} from './reportCredentialSensitiveFailure'
import {
  useSilentLoginRestore,
  type SilentLoginRestoreStatus,
} from './useSilentLoginRestore'

export type UseIdentityLifecycleOptions = {
  shellStoreHydrated: boolean
  selectedGameId: string | null
  /** When null or finished, unfinished refresh is skipped. */
  isGameFinished: boolean | null
  refreshUnfinishedSelectedGame: () => void
  turnEnsureIsError: boolean
  turnEnsureError: unknown
}

/**
 * Silent login restore, unfinished-game refresh after identity, and mid-session
 * credential-required handling (clear session + open login modal).
 */
export function useIdentityLifecycle({
  shellStoreHydrated,
  selectedGameId,
  isGameFinished,
  refreshUnfinishedSelectedGame,
  turnEnsureIsError,
  turnEnsureError,
}: UseIdentityLifecycleOptions): {
  silentLoginStatus: SilentLoginRestoreStatus
  forceLoginModalOpen: boolean
  clearForceLoginModalOpen: () => void
  handleIdentityEstablished: () => void
} {
  const {
    status: silentLoginStatus,
    shouldOpenLoginModal,
    clearShouldOpenLoginModal,
  } = useSilentLoginRestore(shellStoreHydrated)

  const credentialRequiredForceLogin = useCredentialRequiredLoginStore(
    (s) => s.forceLoginModal
  )
  const clearCredentialRequiredForceLogin = useCredentialRequiredLoginStore(
    (s) => s.clearForceLoginModal
  )

  const didSilentUnfinishedRefreshRef = useRef(false)
  useEffect(() => {
    if (silentLoginStatus !== 'restored') return
    if (didSilentUnfinishedRefreshRef.current) return
    if (!selectedGameId || isGameFinished == null || isGameFinished) return
    didSilentUnfinishedRefreshRef.current = true
    refreshUnfinishedSelectedGame()
  }, [
    silentLoginStatus,
    selectedGameId,
    isGameFinished,
    refreshUnfinishedSelectedGame,
  ])

  useEffect(() => {
    if (!turnEnsureIsError || turnEnsureError == null) return
    reportCredentialSensitiveFailure(turnEnsureError)
  }, [turnEnsureIsError, turnEnsureError])

  const handleIdentityEstablished = useCallback(() => {
    refreshUnfinishedSelectedGame()
  }, [refreshUnfinishedSelectedGame])

  const clearForceLoginModalOpen = useCallback(() => {
    clearShouldOpenLoginModal()
    clearCredentialRequiredForceLogin()
  }, [clearShouldOpenLoginModal, clearCredentialRequiredForceLogin])

  return {
    silentLoginStatus,
    forceLoginModalOpen: shouldOpenLoginModal || credentialRequiredForceLogin,
    clearForceLoginModalOpen,
    handleIdentityEstablished,
  }
}
