import { describe, it, expect, vi, afterEach } from 'vitest'
import { createLocalStorageOrMemoryStateStorage } from './browserPersistStorage'

describe('createLocalStorageOrMemoryStateStorage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses in-memory storage when localStorage is unusable at probe time', () => {
    const throwing = {
      getItem: vi.fn(() => null),
      setItem: vi.fn(() => {
        throw new Error('blocked')
      }),
      removeItem: vi.fn(),
      clear: vi.fn(),
      length: 0,
      key: vi.fn(),
    }
    vi.stubGlobal('localStorage', throwing)

    const storage = createLocalStorageOrMemoryStateStorage()
    storage.setItem('planets-console-display-preferences', '{"state":{"x":1},"version":0}')
    expect(storage.getItem('planets-console-display-preferences')).toBe(
      '{"state":{"x":1},"version":0}'
    )
  })

  it('reads and writes via localStorage when the probe succeeds', () => {
    const storage = createLocalStorageOrMemoryStateStorage()
    const key = 'planets-console-test-key'
    const value = '{"hello":true}'
    try {
      storage.setItem(key, value)
      expect(storage.getItem(key)).toBe(value)
    } finally {
      try {
        window.localStorage.removeItem(key)
      } catch {
        // ignore
      }
    }
  })
})
