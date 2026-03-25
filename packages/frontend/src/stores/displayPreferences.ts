import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const displayPreferencesPersistStorage = createLocalStorageOrMemoryStateStorage()

export type PlayerListLabelMode =
  | 'player_names_only'
  | 'race_names_only'
  | 'player_and_race_names'

export type SectorListLabelMode =
  | 'sector_ids_only'
  | 'sector_names_only'
  | 'both_ids_and_names'

type DisplayPreferencesState = {
  playerListLabelMode: PlayerListLabelMode
  sectorListLabelMode: SectorListLabelMode
  setPlayerListLabelMode: (mode: PlayerListLabelMode) => void
  setSectorListLabelMode: (mode: SectorListLabelMode) => void
}

export const useDisplayPreferencesStore = create<DisplayPreferencesState>()(
  persist(
    (set) => ({
      playerListLabelMode: 'player_names_only',
      sectorListLabelMode: 'sector_ids_only',
      setPlayerListLabelMode: (playerListLabelMode) => set({ playerListLabelMode }),
      setSectorListLabelMode: (sectorListLabelMode) => set({ sectorListLabelMode }),
    }),
    {
      name: 'planets-console-display-preferences',
      storage: createJSONStorage(() => displayPreferencesPersistStorage),
    }
  )
)
