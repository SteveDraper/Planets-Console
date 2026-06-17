import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  usePersistStoreHydrated,
  type PersistHydratableStore,
} from './usePersistStoreHydrated'

function createMockPersistStore(initialHydrated: boolean) {
  let hydrated = initialHydrated
  const finishListeners = new Set<() => void>()

  const store: PersistHydratableStore = {
    persist: {
      hasHydrated: () => hydrated,
      onFinishHydration: (fn) => {
        finishListeners.add(fn)
        return () => {
          finishListeners.delete(fn)
        }
      },
    },
  }

  const finishHydration = () => {
    hydrated = true
    for (const fn of finishListeners) {
      fn()
    }
  }

  return { store, finishHydration }
}

describe('usePersistStoreHydrated', () => {
  it('returns true when the store is already hydrated', () => {
    const { store } = createMockPersistStore(true)

    const { result } = renderHook(() => usePersistStoreHydrated(store))

    expect(result.current).toBe(true)
  })

  it('returns false until hydration finishes', () => {
    const { store, finishHydration } = createMockPersistStore(false)

    const { result } = renderHook(() => usePersistStoreHydrated(store))
    expect(result.current).toBe(false)

    act(() => {
      finishHydration()
    })

    expect(result.current).toBe(true)
  })

  it('re-syncs hasHydrated on mount when hydration completed before subscribe', () => {
    const { store, finishHydration } = createMockPersistStore(false)

    const { result, rerender } = renderHook(() => usePersistStoreHydrated(store))
    expect(result.current).toBe(false)

    act(() => {
      finishHydration()
    })
    expect(result.current).toBe(true)

    rerender()
    expect(result.current).toBe(true)
  })
})
