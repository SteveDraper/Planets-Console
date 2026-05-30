import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const enabledAnalyticsPersistStorage = createLocalStorageOrMemoryStateStorage()

export const ENABLED_ANALYTICS_STORAGE_KEY = 'planets-console-enabled-analytics'

type EnabledAnalyticsState = {
  enabledIds: string[]
  isEnabled: (id: string) => boolean
  toggleEnabled: (id: string) => void
  setEnabled: (id: string, enabled: boolean) => void
}

export const useEnabledAnalyticsStore = create<EnabledAnalyticsState>()(
  persist(
    (set, get) => ({
      enabledIds: [],
      isEnabled: (id) => get().enabledIds.includes(id),
      toggleEnabled: (id) => {
        set((state) => {
          const has = state.enabledIds.includes(id)
          return {
            enabledIds: has
              ? state.enabledIds.filter((existing) => existing !== id)
              : [...state.enabledIds, id],
          }
        })
      },
      setEnabled: (id, enabled) => {
        set((state) => {
          const has = state.enabledIds.includes(id)
          if (enabled && !has) {
            return { enabledIds: [...state.enabledIds, id] }
          }
          if (!enabled && has) {
            return { enabledIds: state.enabledIds.filter((existing) => existing !== id) }
          }
          return state
        })
      },
    }),
    {
      name: ENABLED_ANALYTICS_STORAGE_KEY,
      storage: createJSONStorage(() => enabledAnalyticsPersistStorage),
      partialize: (state) => ({ enabledIds: state.enabledIds }),
    }
  )
)
