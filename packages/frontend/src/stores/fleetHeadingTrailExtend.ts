import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import {
  clampFleetHeadingTrailExtendTurns,
  FLEET_HEADING_TRAIL_MAX_EXTEND_TURNS,
} from '../analytics/fleet/fleetHeadingTrails'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const fleetHeadingTrailExtendPersistStorage = createLocalStorageOrMemoryStateStorage()

export const FLEET_HEADING_TRAIL_EXTEND_STORAGE_KEY =
  'planets-console-fleet-heading-trail-extend'

export { FLEET_HEADING_TRAIL_MAX_EXTEND_TURNS }

type FleetHeadingTrailExtendState = {
  /** Extra turns beyond the current-turn segment (0 = current only). */
  extendTurns: number
  setExtendTurns: (extendTurns: number) => void
}

export const useFleetHeadingTrailExtendStore = create<FleetHeadingTrailExtendState>()(
  persist(
    (set) => ({
      extendTurns: 0,
      setExtendTurns: (extendTurns) =>
        set({ extendTurns: clampFleetHeadingTrailExtendTurns(extendTurns) }),
    }),
    {
      name: FLEET_HEADING_TRAIL_EXTEND_STORAGE_KEY,
      storage: createJSONStorage(() => fleetHeadingTrailExtendPersistStorage),
      partialize: (state) => ({ extendTurns: state.extendTurns }),
      merge: (persisted, current) => {
        const raw =
          persisted != null &&
          typeof persisted === 'object' &&
          'extendTurns' in persisted
            ? (persisted as { extendTurns: unknown }).extendTurns
            : current.extendTurns
        return {
          ...current,
          extendTurns: clampFleetHeadingTrailExtendTurns(
            typeof raw === 'number' ? raw : 0
          ),
        }
      },
    }
  )
)
