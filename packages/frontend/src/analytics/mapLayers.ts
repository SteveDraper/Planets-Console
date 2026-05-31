import type { CombinedMapData, ConnectionsMapParams, MapDataResponse, MapEdge } from '../api/bff'
import {
  defaultCartographyLayerVisibility,
  EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
  type CartographyLayerVisibility,
  type StellarCartographySettingsGates,
} from './stellar-cartography/layers'
import {
  defaultWormholeDisplayMode,
  type WormholeDisplayMode,
} from './stellar-cartography/wormholeDisplayMode'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
  type ClusterOutlineDisplayMode,
} from './stellar-cartography/clusterOutlineDisplayMode'
import { routeWaypointsFromMap } from './connections/mapLayer'
import { applyFutureIonStormOverlayPositions } from '../lib/cartography/futureTurnIonStorms'
import {
  mapLayerMergerFor,
  type MapLayerMergeContext,
} from './mapAnalyticRegistry'
import { BASE_MAP_ANALYTIC_ID } from './mapAnalyticIds'

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
  /**
   * Layer visibility and display modes for the Stellar Cartography merge.
   * When omitted, the cartography merger uses {@link defaultStellarCartographyMapMergeOptions}.
   */
  stellarCartography?: StellarCartographyMapMergeOptions
}

/** Static defaults used when cartography merge options are not supplied by the caller. */
export function defaultStellarCartographyMapMergeOptions(): StellarCartographyMapMergeOptions {
  return {
    layerVisibility: defaultCartographyLayerVisibility(),
    settingsGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
    wormholeDisplayMode: defaultWormholeDisplayMode(),
    starClusterDisplayMode: defaultStarClusterDisplayMode(),
    neutronClusterDisplayMode: defaultNeutronClusterDisplayMode(),
  }
}

export function combineMapData(
  analyticIds: readonly string[],
  results: { data?: MapDataResponse }[],
  options: CombineMapDataOptionsBase
): CombinedMapData {
  const baseMapAnalyticId = analyticIds.find((id) => id === BASE_MAP_ANALYTIC_ID) ?? null
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
    const slotId = analyticIds[idx] ?? ''
    if (!data || slotId === '') return
    mapLayerMergerFor(slotId)(data, context, options, slotId)
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
