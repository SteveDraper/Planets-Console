import { useEffect, useState } from 'react'

export type PersistHydratableStore = {
  persist: {
    hasHydrated: () => boolean
    onFinishHydration: (fn: () => void) => () => void
  }
}

/** Tracks Zustand persist rehydration so queries can wait for stored shell state. */
export function usePersistStoreHydrated(store: PersistHydratableStore): boolean {
  const [hydrated, setHydrated] = useState(() => store.persist.hasHydrated())
  useEffect(() => {
    const unsub = store.persist.onFinishHydration(() => {
      setHydrated(true)
    })
    setHydrated(store.persist.hasHydrated())
    return unsub
  }, [store])
  return hydrated
}
