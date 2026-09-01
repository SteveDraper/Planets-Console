import { create } from 'zustand'
import type { ConnectionsMapParams } from './api'

/** Ephemeral Connections map GET knobs. Not persisted. */
export const DEFAULT_CONNECTIONS_MAP_PARAMS: ConnectionsMapParams = {
  warpSpeed: 9,
  gravitonicMovement: false,
  flareMode: 'include',
  flareDepth: 2,
}

type ConnectionsMapParamsState = {
  connectionsMapParams: ConnectionsMapParams
  setConnectionsMapParams: (next: ConnectionsMapParams) => void
}

export const useConnectionsMapParamsStore = create<ConnectionsMapParamsState>()((set) => ({
  connectionsMapParams: DEFAULT_CONNECTIONS_MAP_PARAMS,
  setConnectionsMapParams: (connectionsMapParams) => set({ connectionsMapParams }),
}))
