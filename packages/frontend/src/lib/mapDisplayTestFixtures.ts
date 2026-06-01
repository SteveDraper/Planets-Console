import type { CombinedMapData } from '../api/bff'

export const sampleMap: CombinedMapData = {
  nodes: [{ id: 'base-map:1', label: 'A', x: 1, y: 2 }],
  edges: [],
  routeWaypoints: [],
  overlayCircles: [],
  wormholeUnknownEntrances: [],
}

export const turnTwoMap: CombinedMapData = {
  ...sampleMap,
  nodes: [{ id: 'base-map:1', label: 'A', x: 3, y: 4 }],
}

export const emptyCombined: CombinedMapData = { ...sampleMap, nodes: [] }

export const defaultRetentionScope = { gameId: 'g1', perspective: 1 }

export const defaultMapIds = ['base-map', 'connections'] as const

export const idleMapLoad = {
  turnDataReady: true,
  turnEnsurePending: false,
  mapPending: false,
  mapHasError: false,
  mapHasAnyData: true,
  mapError: null,
}

export const initialMapLoad = {
  turnDataReady: true,
  turnEnsurePending: false,
  mapPending: true,
  mapHasError: false,
  mapHasAnyData: false,
  mapError: null,
}
