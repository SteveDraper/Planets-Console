import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const persistStorage = createLocalStorageOrMemoryStateStorage()

export const TEAM_INFORMATION_PREFERENCES_STORAGE_KEY =
  'planets-console-team-information-preferences'

const PERSIST_VERSION = 3

type TeamInformationPreferencesState = {
  /** When true, paint the owned-planets site set. Default off. Global. */
  ownedPlanetsOnly: boolean
  /**
   * League team ids whose territory fill is hidden.
   * Absent ids stay visible, so every team starts checked. Global.
   */
  hiddenLeagueTeamIds: number[]
  /**
   * Game ids whose Territory paint is the league-team partition.
   * A missing id is off (player territory). Only ``true`` is stored.
   */
  byTeamByGameId: Record<string, boolean>
  setOwnedPlanetsOnly: (ownedPlanetsOnly: boolean) => void
  setLeagueTeamRegionVisible: (leagueTeamId: number, visible: boolean) => void
  setByTeamForGame: (gameId: string, byTeam: boolean) => void
}

type TeamInformationPreferencesPersisted = Pick<
  TeamInformationPreferencesState,
  'ownedPlanetsOnly' | 'hiddenLeagueTeamIds' | 'byTeamByGameId'
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

/** Keep only game ids explicitly set to by-team. Missing and false read as off. */
export function sanitizeByTeamByGameId(value: unknown): Record<string, boolean> {
  if (value == null || typeof value !== 'object' || Array.isArray(value)) return {}
  const byGameId: Record<string, boolean> = {}
  for (const [gameId, flag] of Object.entries(value)) {
    if (gameId.length > 0 && flag === true) byGameId[gameId] = true
  }
  return byGameId
}

/** Off when there is no open game or this game has no stored true. */
export function byTeamForGame(
  byTeamByGameId: Readonly<Record<string, boolean>>,
  gameId: string | null
): boolean {
  if (gameId == null || gameId.length === 0) return false
  return byTeamByGameId[gameId] === true
}

function persistedFromUnknown(persisted: unknown): TeamInformationPreferencesPersisted {
  const raw = persisted as {
    ownedPlanetsOnly?: unknown
    hiddenLeagueTeamIds?: unknown
    byTeamByGameId?: unknown
  } | null
  return {
    ownedPlanetsOnly: raw?.ownedPlanetsOnly === true,
    hiddenLeagueTeamIds: sanitizeHiddenLeagueTeamIds(raw?.hiddenLeagueTeamIds),
    byTeamByGameId: sanitizeByTeamByGameId(raw?.byTeamByGameId),
  }
}

export const useTeamInformationPreferencesStore = create<TeamInformationPreferencesState>()(
  persist(
    (set) => ({
      ownedPlanetsOnly: false,
      hiddenLeagueTeamIds: [],
      byTeamByGameId: {},
      setOwnedPlanetsOnly: (ownedPlanetsOnly) => set({ ownedPlanetsOnly }),
      setLeagueTeamRegionVisible: (leagueTeamId, visible) =>
        set((state) => {
          const hidden = new Set(state.hiddenLeagueTeamIds)
          if (visible) hidden.delete(leagueTeamId)
          else hidden.add(leagueTeamId)
          return { hiddenLeagueTeamIds: sanitizeHiddenLeagueTeamIds([...hidden]) }
        }),
      setByTeamForGame: (gameId, byTeam) =>
        set((state) => {
          if (gameId.length === 0) return state
          const byTeamByGameId = { ...state.byTeamByGameId }
          if (byTeam) byTeamByGameId[gameId] = true
          else delete byTeamByGameId[gameId]
          return { byTeamByGameId }
        }),
    }),
    {
      name: TEAM_INFORMATION_PREFERENCES_STORAGE_KEY,
      version: PERSIST_VERSION,
      storage: createJSONStorage(() => persistStorage),
      partialize: (state) => ({
        ownedPlanetsOnly: state.ownedPlanetsOnly,
        hiddenLeagueTeamIds: state.hiddenLeagueTeamIds,
        byTeamByGameId: state.byTeamByGameId,
      }),
      merge: (persisted, current) => ({
        ...current,
        ...persistedFromUnknown(persisted),
      }),
      migrate: (persisted) => persistedFromUnknown(persisted),
    }
  )
)
