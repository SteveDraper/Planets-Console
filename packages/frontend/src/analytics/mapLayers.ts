import type { CombinedMapData, ConnectionsMapParams, MapDataResponse, MapEdge } from '../api/bff'
import type {
  CartographyLayerVisibility,
  StellarCartographySettingsGates,
} from './stellar-cartography/layers'
import type { WormholeDisplayMode } from './stellar-cartography/wormholeDisplayMode'
import type { ClusterOutlineDisplayMode } from './stellar-cartography/clusterOutlineDisplayMode'
import { routeWaypointsFromMap } from './connections/mapLayer'
import { applyFutureIonStormOverlayPositions } from '../lib/cartography/futureTurnIonStorms'
import {
  mapLayerMergerFor,
  type MapLayerMergeContext,
} from './mapAnalyticRegistry'

export type StellarCartographyMapMergeOptions = {
  layerVisibility: CartographyLayerVisibility
  settingsGates: StellarCartographySettingsGates
  wormholeDisplayMode: WormholeDisplayMode
  starClusterDisplayMode: ClusterOutlineDisplayMode
  neutronClusterDisplayMode: ClusterOutlineDisplayMode
}

export type CombineMapDataOptionsBase = {
  /** When set, connection routes are clipped to match the UI flare mode if the response is stale. */
  liveConnectionsParams: ConnectionsMapParams | null
  /** Extrapolate ion storm positions forward from the latest stored turn. */
  futureTurnOffset?: number
  stellarCartography?: StellarCartographyMapMergeOptions
}

export type CombineMapDataOptionsWithStellarCartography = CombineMapDataOptionsBase & {
  stellarCartography: StellarCartographyMapMergeOptions
}

export function combineMapData(
  analyticIds: readonly string[],
  results: { data?: MapDataResponse }[],
  options: CombineMapDataOptionsBase
): CombinedMapData
export function combineMapData<T extends readonly string[]>(
  analyticIds: T,
  results: { data?: MapDataResponse }[],
  options: 'stellar-cartography' extends T[number]
    ? CombineMapDataOptionsWithStellarCartography
    : CombineMapDataOptionsBase
): CombinedMapData
export function combineMapData(
  analyticIds: readonly string[],
  results: { data?: MapDataResponse }[],
  options: CombineMapDataOptionsBase
): CombinedMapData {
  const baseMapAnalyticId = analyticIds.find((id) => id === 'base-map') ?? null
  const nodes: CombinedMapData['nodes'] = []
  const edges: MapEdge[] = []
  const overlayCircles: CombinedMapData['overlayCircles'] = []
  const wormholeUnknownEntrances: CombinedMapData['wormholeUnknownEntrances'] = []
  const context: MapLayerMergeContext = {
    baseMapAnalyticId,
    nodes,
    edges,
    overlayCircles,
    wormholeUnknownEntrances,
    waypointsByKey: new Map<string, { x: number; y: number }>(),
    nuIonStorms: undefined,
  }
  results.forEach((result, idx) => {
    const data = result.data
    const prefix = analyticIds[idx] ?? ''
    if (!data) return
    mapLayerMergerFor(data.analyticId)(data, context, options, prefix)
  })
  const futureTurnOffset = options.futureTurnOffset ?? 0
  const overlayCirclesWithFuture =
    futureTurnOffset > 0
      ? applyFutureIonStormOverlayPositions(context.overlayCircles, futureTurnOffset)
      : context.overlayCircles
  return {
    nodes,
    edges,
    routeWaypoints: routeWaypointsFromMap(context.waypointsByKey),
    overlayCircles: overlayCirclesWithFuture,
    wormholeUnknownEntrances,
    nuIonStorms: context.nuIonStorms,
  }
}
