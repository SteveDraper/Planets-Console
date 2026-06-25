import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import {
  fleetPlayerVisibilityStorageKey,
  resolveFleetPlayerVisible,
  type FleetPlayerVisibilityOverrides,
} from '../analytics/fleet/fleetPlayerVisibilityPolicy'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const fleetPlayerVisibilityPersistStorage = createLocalStorageOrMemoryStateStorage()

export const FLEET_PLAYER_VISIBILITY_STORAGE_KEY = 'planets-console-fleet-player-visibility'

type FleetPlayerVisibilityState = {
  overrides: FleetPlayerVisibilityOverrides
  isFleetPlayerVisible: (playerId: number, viewpointPlayerId: number | null) => boolean
  setFleetPlayerVisible: (playerId: number, enabled: boolean) => void
}

export const useFleetPlayerVisibilityStore = create<FleetPlayerVisibilityState>()(
  persist(
    (set, get) => ({
      overrides: {},
      isFleetPlayerVisible: (playerId, viewpointPlayerId) =>
        resolveFleetPlayerVisible(playerId, viewpointPlayerId, get().overrides),
      setFleetPlayerVisible: (playerId, enabled) =>
        set((state) => ({
          overrides: {
            ...state.overrides,
            [fleetPlayerVisibilityStorageKey(playerId)]: enabled,
          },
        })),
    }),
    {
      name: FLEET_PLAYER_VISIBILITY_STORAGE_KEY,
      storage: createJSONStorage(() => fleetPlayerVisibilityPersistStorage),
      partialize: (state) => ({ overrides: state.overrides }),
    }
  )
)
