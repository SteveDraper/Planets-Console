/**
 * Mid-session credential-required handling shared by identity lifecycle and
 * shell game selection (clear session + request login modal).
 */
import { create } from 'zustand'
import { isCredentialRequiredError } from '../api/bffHttpError'
import { useSessionStore } from '../stores/session'

type CredentialRequiredLoginState = {
  forceLoginModal: boolean
  requestLoginModal: () => void
  clearForceLoginModal: () => void
}

export const useCredentialRequiredLoginStore = create<CredentialRequiredLoginState>((set) => ({
  forceLoginModal: false,
  requestLoginModal: () => set({ forceLoginModal: true }),
  clearForceLoginModal: () => set({ forceLoginModal: false }),
}))

/** Clear session + open login modal when err is credential-required; else false. */
export function reportCredentialSensitiveFailure(err: unknown): boolean {
  if (!isCredentialRequiredError(err)) {
    return false
  }
  useSessionStore.getState().clearSession()
  useCredentialRequiredLoginStore.getState().requestLoginModal()
  return true
}
