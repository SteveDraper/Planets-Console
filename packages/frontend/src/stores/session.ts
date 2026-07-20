import { create } from 'zustand'

/**
 * Session credentials for planets.nu. In-memory only; never persisted.
 * Password must not be stored in localStorage, sessionStorage, cookies, or URL.
 * After login exchange the password is cleared; silent restore / name-only switch
 * set the name only.
 */
type SessionState = {
  name: string | null
  /** Always null in SPA flows; retained for historical session shape. */
  password: string | null
  /** Bumps on credential changes so turn-ensure queries refetch without password in the key. */
  credentialsRevision: number
  /** Adopt a login name with no password (silent restore / name-only switch / post-exchange). */
  adoptLoginName: (name: string) => void
  clearSession: () => void
}

export const useSessionStore = create<SessionState>((set) => ({
  name: null,
  password: null,
  credentialsRevision: 0,
  adoptLoginName: (name) => {
    const trimmed = name.trim()
    set((state) => ({
      name: trimmed === '' ? null : trimmed,
      password: null,
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