import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { ScoresTableParams } from '../api/bff'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const scoresTablePreferencesPersistStorage = createLocalStorageOrMemoryStateStorage()

export const SCORES_TABLE_PREFERENCES_STORAGE_KEY = 'planets-console-scores-table-preferences'

type ScoresTablePreferencesState = {
  scoresTableParams: ScoresTableParams
  setScoresTableParams: (next: ScoresTableParams) => void
}

export const useScoresTablePreferencesStore = create<ScoresTablePreferencesState>()(
  persist(
    (set) => ({
      scoresTableParams: { includeBuildInference: false },
      setScoresTableParams: (scoresTableParams) => set({ scoresTableParams }),
    }),
    {
      name: SCORES_TABLE_PREFERENCES_STORAGE_KEY,
      storage: createJSONStorage(() => scoresTablePreferencesPersistStorage),
      partialize: (state) => ({ scoresTableParams: state.scoresTableParams }),
    }
  )
)
