import { create } from 'zustand'

/**
 * Session credentials for planets.nu. In-memory only; never persisted.
 * Password must not be stored in localStorage, sessionStorage, cookies, or URL.
 */
type SessionState = {
  name: string | null
  password: string | null
  setCredentials: (name: string, password: string) => void
  clearSession: () => void
}

export const useSessionStore = create<SessionState>((set) => ({
  name: null,
  password: null,
  setCredentials: (name, password) => set({ name, password }),
  clearSession: () => set({ name: null, password: null }),
}))
