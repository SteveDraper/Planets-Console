import type { StateStorage } from 'zustand/middleware'

function createInMemoryStateStorage(): StateStorage {
  const values = new Map<string, string>()
  return {
    getItem: (name) => values.get(name) ?? null,
    setItem: (name, value) => {
      values.set(name, value)
    },
    removeItem: (name) => {
      values.delete(name)
    },
  }
}

function localStorageProbe(): boolean {
  if (typeof window === 'undefined') {
    return false
  }
  try {
    const key = '__planets_console_storage_probe__'
    window.localStorage.setItem(key, key)
    window.localStorage.removeItem(key)
    return true
  } catch {
    return false
  }
}

/**
 * Storage backend for zustand `persist` + `createJSONStorage`.
 * Uses `localStorage` when available; on failure (private mode, blocked storage, no `window`)
 * falls back to an in-memory map so init and rehydration never throw.
 */
export function createLocalStorageOrMemoryStateStorage(): StateStorage {
  if (!localStorageProbe()) {
    return createInMemoryStateStorage()
  }

  return {
    getItem(name) {
      try {
        return window.localStorage.getItem(name)
      } catch {
        return null
      }
    },
    setItem(name, value) {
      try {
        window.localStorage.setItem(name, value)
      } catch {
        // Quota, security errors, etc. -- in-memory zustand state still updates.
      }
    },
    removeItem(name) {
      try {
        window.localStorage.removeItem(name)
      } catch {
        // ignore
      }
    },
  }
}
