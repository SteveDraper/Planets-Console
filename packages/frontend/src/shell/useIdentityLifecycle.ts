import { useCallback, useEffect, useRef, useState } from 'react'
import { isCredentialRequiredError } from '../api/bffHttpError'
import { useSessionStore } from '../stores/session'
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
  /** Clear session + open login modal when err is credential-required; else false. */
  reportCredentialSensitiveFailure: (err: unknown) => boolean
} {
  const {
    status: silentLoginStatus,
    shouldOpenLoginModal,
    clearShouldOpenLoginModal,
  } = useSilentLoginRestore(shellStoreHydrated)

  const [authFailureLoginModal, setAuthFailureLoginModal] = useState(false)

  const openLoginModalForCredentialFailure = useCallback(() => {
    useSessionStore.getState().clearSession()
    setAuthFailureLoginModal(true)
  }, [])

  const reportCredentialSensitiveFailure = useCallback(
    (err: unknown): boolean => {
      if (!isCredentialRequiredError(err)) {
        return false
      }
      openLoginModalForCredentialFailure()
      return true
    },
    [openLoginModalForCredentialFailure]
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
  }, [turnEnsureIsError, turnEnsureError, reportCredentialSensitiveFailure])

  const handleIdentityEstablished = useCallback(() => {
    refreshUnfinishedSelectedGame()
  }, [refreshUnfinishedSelectedGame])

  const clearForceLoginModalOpen = useCallback(() => {
    clearShouldOpenLoginModal()
    setAuthFailureLoginModal(false)
  }, [clearShouldOpenLoginModal])

  return {
    silentLoginStatus,
    forceLoginModalOpen: shouldOpenLoginModal || authFailureLoginModal,
    clearForceLoginModalOpen,
    handleIdentityEstablished,
    reportCredentialSensitiveFailure,
  }
}
