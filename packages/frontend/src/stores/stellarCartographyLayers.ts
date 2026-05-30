import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import {
  defaultCartographyLayerVisibility,
  type CartographyLayerId,
  type CartographyLayerVisibility,
} from '../analytics/stellar-cartography/layers'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
  migratePersistedClusterLayers,
  type ClusterOutlineDisplayMode,
} from '../analytics/stellar-cartography/clusterOutlineDisplayMode'
import {
  defaultWormholeDisplayMode,
  migratePersistedWormholeLayer,
  type WormholeDisplayMode,
} from '../analytics/stellar-cartography/wormholeDisplayMode'
import { createLocalStorageOrMemoryStateStorage } from '../lib/browserPersistStorage'

const stellarCartographyLayersPersistStorage = createLocalStorageOrMemoryStateStorage()

export const STELLAR_CARTOGRAPHY_LAYERS_STORAGE_KEY =
  'planets-console-stellar-cartography-layers'

const PERSIST_VERSION = 3

type BooleanLayerId = Exclude<
  CartographyLayerId,
  'wormholes' | 'star-clusters' | 'neutron-clusters'
>

type StellarCartographyLayersState = {
  layers: CartographyLayerVisibility
  wormholeDisplayMode: WormholeDisplayMode
  starClusterDisplayMode: ClusterOutlineDisplayMode
  neutronClusterDisplayMode: ClusterOutlineDisplayMode
  isLayerEnabled: (layerId: CartographyLayerId) => boolean
  setLayerEnabled: (layerId: BooleanLayerId, enabled: boolean) => void
  setWormholeDisplayMode: (mode: WormholeDisplayMode) => void
  setStarClusterDisplayMode: (mode: ClusterOutlineDisplayMode) => void
  setNeutronClusterDisplayMode: (mode: ClusterOutlineDisplayMode) => void
}

type StellarCartographyLayersPersisted = Pick<
  StellarCartographyLayersState,
  'layers' | 'wormholeDisplayMode' | 'starClusterDisplayMode' | 'neutronClusterDisplayMode'
>

function migratePersistedState(persisted: unknown, version: number): StellarCartographyLayersPersisted {
  const raw = persisted as {
    layers?: Record<string, unknown>
    wormholeDisplayMode?: WormholeDisplayMode
    starClusterDisplayMode?: ClusterOutlineDisplayMode
    neutronClusterDisplayMode?: ClusterOutlineDisplayMode
  }

  let layers = raw.layers
  let wormholeDisplayMode = raw.wormholeDisplayMode
  let starClusterDisplayMode = raw.starClusterDisplayMode
  let neutronClusterDisplayMode = raw.neutronClusterDisplayMode

  if (version < 2) {
    const wormholeMigrated = migratePersistedWormholeLayer(layers, wormholeDisplayMode)
    layers = wormholeMigrated.layers
    wormholeDisplayMode = wormholeMigrated.wormholeDisplayMode
  }

  if (version < 3) {
    const clusterMigrated = migratePersistedClusterLayers(
      layers,
      starClusterDisplayMode,
      neutronClusterDisplayMode
    )
    layers = clusterMigrated.layers
    starClusterDisplayMode = clusterMigrated.starClusterDisplayMode
    neutronClusterDisplayMode = clusterMigrated.neutronClusterDisplayMode
  }

  return {
    layers: {
      ...defaultCartographyLayerVisibility(),
      ...layers,
    } as CartographyLayerVisibility,
    wormholeDisplayMode: wormholeDisplayMode ?? defaultWormholeDisplayMode(),
    starClusterDisplayMode: starClusterDisplayMode ?? defaultStarClusterDisplayMode(),
    neutronClusterDisplayMode: neutronClusterDisplayMode ?? defaultNeutronClusterDisplayMode(),
  }
}

export const useStellarCartographyLayersStore = create<StellarCartographyLayersState>()(
  persist(
    (set, get) => ({
      layers: defaultCartographyLayerVisibility(),
      wormholeDisplayMode: defaultWormholeDisplayMode(),
      starClusterDisplayMode: defaultStarClusterDisplayMode(),
      neutronClusterDisplayMode: defaultNeutronClusterDisplayMode(),
      isLayerEnabled: (layerId) => {
        if (layerId === 'wormholes') {
          return get().wormholeDisplayMode !== 'off'
        }
        if (layerId === 'star-clusters') {
          return get().starClusterDisplayMode !== 'off'
        }
        if (layerId === 'neutron-clusters') {
          return get().neutronClusterDisplayMode !== 'off'
        }
        return get().layers[layerId] ?? true
      },
      setLayerEnabled: (layerId, enabled) =>
        set((state) => ({
          layers: { ...state.layers, [layerId]: enabled },
        })),
      setWormholeDisplayMode: (mode) => set({ wormholeDisplayMode: mode }),
      setStarClusterDisplayMode: (mode) => set({ starClusterDisplayMode: mode }),
      setNeutronClusterDisplayMode: (mode) => set({ neutronClusterDisplayMode: mode }),
    }),
    {
      name: STELLAR_CARTOGRAPHY_LAYERS_STORAGE_KEY,
      version: PERSIST_VERSION,
      storage: createJSONStorage(() => stellarCartographyLayersPersistStorage),
      partialize: (state) => ({
        layers: state.layers,
        wormholeDisplayMode: state.wormholeDisplayMode,
        starClusterDisplayMode: state.starClusterDisplayMode,
        neutronClusterDisplayMode: state.neutronClusterDisplayMode,
      }),
      migrate: (persisted, version) => {
        if (version >= PERSIST_VERSION) return persisted as StellarCartographyLayersPersisted
        return migratePersistedState(persisted, version)
      },
    }
  )
)
