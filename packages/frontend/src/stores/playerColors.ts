import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import {
  colorForPlayerId,
  colorFromOverrideOrDefault,
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
      colorForPlayerId: (playerId) =>
        colorFromOverrideOrDefault(
          playerId,
          get().overrides[playerColorOverrideStorageKey(playerId)]
        ),
    }),
    {
      name: PLAYER_COLORS_STORAGE_KEY,
      storage: createJSONStorage(() => playerColorsPersistStorage),
      partialize: (state) => ({ overrides: state.overrides }),
    }
  )
)

/**
 * Bind zustand overrides into the shared {@link colorForPlayerId} storage port.
 * Settings (or another always-mounted shell module) must import this module so
 * the port is installed and persisted overrides rehydrate.
 */
export function installPlayerColorsStorePort(): void {
  setPlayerColorOverrideStore({
    getOverride: (playerId) =>
      usePlayerColorsStore.getState().overrides[playerColorOverrideStorageKey(playerId)],
  })
}

installPlayerColorsStorePort()

/**
 * Reactive player color for map/table paint. Subscribes to override changes so
 * Settings updates re-render; resolution still goes through {@link colorForPlayerId}.
 */
export function usePlayerColor(playerId: number): string {
  // Subscribe so Settings override edits re-render; hex still comes from the port.
  usePlayerColorsStore(
    (state) => state.overrides[playerColorOverrideStorageKey(playerId)] ?? null
  )
  return colorForPlayerId(playerId)
}
