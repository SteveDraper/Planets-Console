import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const persistStorage = createLocalStorageOrMemoryStateStorage()

export const TEAM_INFORMATION_PREFERENCES_STORAGE_KEY =
  'planets-console-team-information-preferences'

const PERSIST_VERSION = 1

type TeamInformationPreferencesState = {
  /** When true, paint ``team-territory-owned-only``. Default off. */
  ownedPlanetsOnly: boolean
  setOwnedPlanetsOnly: (ownedPlanetsOnly: boolean) => void
}

type TeamInformationPreferencesPersisted = Pick<
  TeamInformationPreferencesState,
  'ownedPlanetsOnly'
>

function migratePersistedState(persisted: unknown): TeamInformationPreferencesPersisted {
  const raw = persisted as { ownedPlanetsOnly?: unknown }
  return { ownedPlanetsOnly: raw?.ownedPlanetsOnly === true }
}

export const useTeamInformationPreferencesStore = create<TeamInformationPreferencesState>()(
  persist(
    (set) => ({
      ownedPlanetsOnly: false,
      setOwnedPlanetsOnly: (ownedPlanetsOnly) => set({ ownedPlanetsOnly }),
    }),
    {
      name: TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
      version: PERSIST_VERSION,
      storage: createJSONStorage(() => persistStorage),
      partialize: (state) => ({ ownedPlanetsOnly: state.ownedPlanetsOnly }),
      migrate: (persisted) => migratePersistedState(persisted),
    }
  )
)
