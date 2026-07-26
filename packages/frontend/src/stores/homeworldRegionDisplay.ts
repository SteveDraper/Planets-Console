import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'
import {
  defaultHomeworldRegionDisplayMode,
  isHomeworldRegionDisplayMode,
  type HomeworldRegionDisplayMode,
} from '../analytics/homeworld-locator/homeworldRegionDisplayMode'

const homeworldRegionDisplayPersistStorage = createLocalStorageOrMemoryStateStorage()

export const HOMEWORLD_REGION_DISPLAY_STORAGE_KEY =
  'planets-console-homeworld-region-display'

const PERSIST_VERSION = 1

type HomeworldRegionDisplayState = {
  regionDisplayMode: HomeworldRegionDisplayMode
  setRegionDisplayMode: (mode: HomeworldRegionDisplayMode) => void
}

type HomeworldRegionDisplayPersisted = Pick<
  HomeworldRegionDisplayState,
  'regionDisplayMode'
>

function migratePersistedState(persisted: unknown): HomeworldRegionDisplayPersisted {
  const raw = persisted as { regionDisplayMode?: unknown }
  return {
    regionDisplayMode: isHomeworldRegionDisplayMode(raw.regionDisplayMode)
      ? raw.regionDisplayMode
      : defaultHomeworldRegionDisplayMode(),
  }
}

export const useHomeworldRegionDisplayStore = create<HomeworldRegionDisplayState>()(
  persist(
    (set) => ({
      regionDisplayMode: defaultHomeworldRegionDisplayMode(),
      setRegionDisplayMode: (mode) => {
        if (!isHomeworldRegionDisplayMode(mode)) return
        set({ regionDisplayMode: mode })
      },
    }),
    {
      name: HOMEWORLD_REGION_DISPLAY_STORAGE_KEY,
      version: PERSIST_VERSION,
      storage: createJSONStorage(() => homeworldRegionDisplayPersistStorage),
      partialize: (state) => ({ regionDisplayMode: state.regionDisplayMode }),
      migrate: (persisted, version) => {
        if (version >= PERSIST_VERSION) {
          return migratePersistedState(persisted)
        }
        return migratePersistedState(persisted)
      },
    }
  )
)
