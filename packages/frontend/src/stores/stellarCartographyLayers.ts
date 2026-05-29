import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import {
  defaultCartographyLayerVisibility,
  type CartographyLayerId,
  type CartographyLayerVisibility,
} from '../analytics/stellar-cartography/layers'
import {
  defaultWormholeDisplayMode,
  migratePersistedWormholeLayer,
  type WormholeDisplayMode,
} from '../analytics/stellar-cartography/wormholeDisplayMode'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const stellarCartographyLayersPersistStorage = createLocalStorageOrMemoryStateStorage()

export const STELLAR_CARTOGRAPHY_LAYERS_STORAGE_KEY =
  'planets-console-stellar-cartography-layers'

const PERSIST_VERSION = 1

type StellarCartographyLayersState = {
  layers: CartographyLayerVisibility
  wormholeDisplayMode: WormholeDisplayMode
  isLayerEnabled: (layerId: CartographyLayerId) => boolean
  setLayerEnabled: (
    layerId: Exclude<CartographyLayerId, 'wormholes'>,
    enabled: boolean
  ) => void
  setWormholeDisplayMode: (mode: WormholeDisplayMode) => void
}

export const useStellarCartographyLayersStore = create<StellarCartographyLayersState>()(
  persist(
    (set, get) => ({
      layers: defaultCartographyLayerVisibility(),
      wormholeDisplayMode: defaultWormholeDisplayMode(),
      isLayerEnabled: (layerId) => {
        if (layerId === 'wormholes') {
          return get().wormholeDisplayMode !== 'off'
        }
        return get().layers[layerId] ?? true
      },
      setLayerEnabled: (layerId, enabled) =>
        set((state) => ({
          layers: { ...state.layers, [layerId]: enabled },
        })),
      setWormholeDisplayMode: (mode) => set({ wormholeDisplayMode: mode }),
    }),
    {
      name: STELLAR_CARTOGRAPHY_LAYERS_STORAGE_KEY,
      version: PERSIST_VERSION,
      storage: createJSONStorage(() => stellarCartographyLayersPersistStorage),
      partialize: (state) => ({
        layers: state.layers,
        wormholeDisplayMode: state.wormholeDisplayMode,
      }),
      migrate: (persisted, version) => {
        if (version >= PERSIST_VERSION) return persisted as StellarCartographyLayersState
        const raw = persisted as {
          layers?: Record<string, unknown>
          wormholeDisplayMode?: WormholeDisplayMode
        }
        const migrated = migratePersistedWormholeLayer(
          raw.layers,
          raw.wormholeDisplayMode
        )
        return {
          layers: {
            ...defaultCartographyLayerVisibility(),
            ...migrated.layers,
          },
          wormholeDisplayMode: migrated.wormholeDisplayMode,
        }
      },
    }
  )
)
