import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { createLocalStorageOrMemoryStateStorage } from '../../lib/browserPersistStorage'
import type { ConnectionsFlareMode, ConnectionsMapParams } from './api'

/**
 * Connections map GET knobs.
 * Only `flareMode` is persisted. Warp, gravitonic movement, and flare depth
 * stay at these defaults after a reload.
 */
export const DEFAULT_CONNECTIONS_MAP_PARAMS: ConnectionsMapParams = {
  warpSpeed: 9,
  gravitonicMovement: false,
  flareMode: 'include',
  flareDepth: 2,
}

export const CONNECTIONS_MAP_PARAMS_STORAGE_KEY = 'planets-console-connections-map-params'

const PERSIST_VERSION = 1

const connectionsMapParamsPersistStorage = createLocalStorageOrMemoryStateStorage()

type ConnectionsMapParamsState = {
  connectionsMapParams: ConnectionsMapParams
  setConnectionsMapParams: (next: ConnectionsMapParams) => void
}

type ConnectionsFlareModePersisted = {
  flareMode: ConnectionsFlareMode
}

const FLARE_MODES: readonly ConnectionsFlareMode[] = ['off', 'include', 'only']

function isConnectionsFlareMode(value: unknown): value is ConnectionsFlareMode {
  return typeof value === 'string' && FLARE_MODES.some((mode) => mode === value)
}

/** Invalid or missing stored values fall back to Show flares (`include`). */
function flareModeFromPersisted(persisted: unknown): ConnectionsFlareMode {
  if (persisted == null || typeof persisted !== 'object') {
    return DEFAULT_CONNECTIONS_MAP_PARAMS.flareMode
  }
  const flareMode = (persisted as { flareMode?: unknown }).flareMode
  return isConnectionsFlareMode(flareMode) ? flareMode : DEFAULT_CONNECTIONS_MAP_PARAMS.flareMode
}

function persistedFromUnknown(persisted: unknown): ConnectionsFlareModePersisted {
  return { flareMode: flareModeFromPersisted(persisted) }
}

export const useConnectionsMapParamsStore = create<ConnectionsMapParamsState>()(
  persist(
    (set) => ({
      connectionsMapParams: DEFAULT_CONNECTIONS_MAP_PARAMS,
      setConnectionsMapParams: (connectionsMapParams) => set({ connectionsMapParams }),
    }),
    {
      name: CONNECTIONS_MAP_PARAMS_STORAGE_KEY,
      version: PERSIST_VERSION,
      storage: createJSONStorage(() => connectionsMapParamsPersistStorage),
      partialize: (state) => ({
        flareMode: state.connectionsMapParams.flareMode,
      }),
      merge: (persisted, current) => ({
        ...current,
        connectionsMapParams: {
          ...current.connectionsMapParams,
          flareMode: flareModeFromPersisted(persisted),
        },
      }),
      migrate: (persisted) => persistedFromUnknown(persisted),
    },
  ),
)
