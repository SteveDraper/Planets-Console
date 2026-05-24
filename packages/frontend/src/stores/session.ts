import { create } from 'zustand'

/**
 * Session credentials for planets.nu. In-memory only; never persisted.
 * Password must not be stored in localStorage, sessionStorage, cookies, or URL.
 */
type SessionState = {
  name: string | null
  password: string | null
  /** Bumps on setCredentials/clearSession so turn-ensure queries refetch without password in the key. */
  credentialsRevision: number
  setCredentials: (name: string, password: string) => void
  clearSession: () => void
}

export const useSessionStore = create<SessionState>((set) => ({
  name: null,
  password: null,
  credentialsRevision: 0,
  setCredentials: (name, password) => {
    const trimmedPassword = password.trim()
    set((state) => ({
      name,
      password: trimmedPassword === '' ? null : trimmedPassword,
      credentialsRevision: state.credentialsRevision + 1,
    }))
  },
  clearSession: () =>
    set((state) => ({
      name: null,
      password: null,
      credentialsRevision: state.credentialsRevision + 1,
    })),
}))
