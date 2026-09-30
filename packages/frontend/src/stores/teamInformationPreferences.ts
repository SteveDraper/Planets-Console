import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const persistStorage = createLocalStorageOrMemoryStateStorage()

export const TEAM_INFORMATION_PREFERENCES_STORAGE_KEY =
  'planets-console-team-information-preferences'

const PERSIST_VERSION = 2

type TeamInformationPreferencesState = {
  /** When true, paint ``team-territory-owned-only``. Default off. */
  ownedPlanetsOnly: boolean
  /**
   * League team ids whose territory fill is hidden.
   * Absent ids stay visible, so every team starts checked.
   */
  hiddenLeagueTeamIds: number[]
  setOwnedPlanetsOnly: (ownedPlanetsOnly: boolean) => void
  setLeagueTeamRegionVisible: (leagueTeamId: number, visible: boolean) => void
}

type TeamInformationPreferencesPersisted = Pick<
  TeamInformationPreferencesState,
  'ownedPlanetsOnly' | 'hiddenLeagueTeamIds'
>

/** Keep positive integer league team ids, sorted and unique. */
export function sanitizeHiddenLeagueTeamIds(value: unknown): number[] {
  if (!Array.isArray(value)) return []
  const ids = new Set<number>()
  for (const entry of value) {
    if (typeof entry === 'number' && Number.isInteger(entry) && entry > 0) {
      ids.add(entry)
    }
  }
  return [...ids].sort((left, right) => left - right)
}

function persistedFromUnknown(persisted: unknown): TeamInformationPreferencesPersisted {
  const raw = persisted as {
    ownedPlanetsOnly?: unknown
    hiddenLeagueTeamIds?: unknown
  } | null
  return {
    ownedPlanetsOnly: raw?.ownedPlanetsOnly === true,
    hiddenLeagueTeamIds: sanitizeHiddenLeagueTeamIds(raw?.hiddenLeagueTeamIds),
  }
}

export const useTeamInformationPreferencesStore = create<TeamInformationPreferencesState>()(
  persist(
    (set) => ({
      ownedPlanetsOnly: false,
      hiddenLeagueTeamIds: [],
      setOwnedPlanetsOnly: (ownedPlanetsOnly) => set({ ownedPlanetsOnly }),
      setLeagueTeamRegionVisible: (leagueTeamId, visible) =>
        set((state) => {
          const hidden = new Set(state.hiddenLeagueTeamIds)
          if (visible) hidden.delete(leagueTeamId)
          else hidden.add(leagueTeamId)
          return { hiddenLeagueTeamIds: sanitizeHiddenLeagueTeamIds([...hidden]) }
        }),
    }),
    {
      name: TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
      version: PERSIST_VERSION,
      storage: createJSONStorage(() => persistStorage),
      partialize: (state) => ({
        ownedPlanetsOnly: state.ownedPlanetsOnly,
        hiddenLeagueTeamIds: state.hiddenLeagueTeamIds,
      }),
      merge: (persisted, current) => ({
        ...current,
        ...persistedFromUnknown(persisted),
      }),
      migrate: (persisted) => persistedFromUnknown(persisted),
    }
  )
)
