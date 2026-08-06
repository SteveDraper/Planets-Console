import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import {
  colorForPlayerId as resolveColorForPlayerId,
  playerColorOverrideStorageKey,
  setPlayerColorOverrideStore,
  type PlayerColorOverrides,
} from '../lib/playerColor'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const playerColorsPersistStorage = createLocalStorageOrMemoryStateStorage()

export const PLAYER_COLORS_STORAGE_KEY = 'planets-console-player-colors'

type PlayerColorsState = {
  overrides: PlayerColorOverrides
  setPlayerColorOverride: (playerId: number, color: string | null) => void
  colorForPlayerId: (playerId: number) => string
}

export const usePlayerColorsStore = create<PlayerColorsState>()(
  persist(
    (set, get) => ({
      overrides: {},
      setPlayerColorOverride: (playerId, color) =>
        set((state) => {
          const key = playerColorOverrideStorageKey(playerId)
          if (color == null || color.length === 0) {
            const rest = { ...state.overrides }
            delete rest[key]
            return { overrides: rest }
          }
          return {
            overrides: {
              ...state.overrides,
              [key]: color,
            },
          }
        }),
      colorForPlayerId: (playerId) => resolveColorForPlayerId(playerId, get().overrides),
    }),
    {
      name: PLAYER_COLORS_STORAGE_KEY,
      storage: createJSONStorage(() => playerColorsPersistStorage),
      partialize: (state) => ({ overrides: state.overrides }),
    }
  )
)

/** Bind zustand overrides into the shared {@link colorForPlayerId} storage port. */
export function installPlayerColorsStorePort(): void {
  setPlayerColorOverrideStore({
    getOverride: (playerId) =>
      usePlayerColorsStore.getState().overrides[playerColorOverrideStorageKey(playerId)],
  })
}

installPlayerColorsStorePort()
