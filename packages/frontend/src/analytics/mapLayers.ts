import type {
  AnalyticShellScope,
  CombinedMapData,
  ConnectionsMapParams,
  MapDataResponse,
  MapEdge,
} from '../api/bff'
import {
  defaultCartographyLayerVisibility,
  EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
  type CartographyLayerVisibility,
  type StellarCartographySettingsGates,
} from './stellar-cartography/layers'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
  type ClusterOutlineDisplayMode,
} from './stellar-cartography/clusterOutlineDisplayMode'
import {
  defaultWormholeDisplayMode,
  type WormholeDisplayMode,
} from './stellar-cartography/wormholeDisplayMode'
import { routeWaypointsFromMap } from './connections/mapLayer'
import { applyFutureIonStormOverlayPositions } from '../lib/cartography/futureTurnIonStorms'
import {
  mapLayerMergerFor,
  type MapLayerMergeContext,
} from './mapAnalyticRegistry'
import { BASE_MAP_ANALYTIC_ID } from './mapAnalyticIds'

/** Cartography layer visibility and display modes for map rendering (not merge). */
export type StellarCartographyMapUiConfig = {
  layerVisibility: CartographyLayerVisibility
  settingsGates: StellarCartographySettingsGates
  wormholeDisplayMode: WormholeDisplayMode
  starClusterDisplayMode: ClusterOutlineDisplayMode
  neutronClusterDisplayMode: ClusterOutlineDisplayMode
}

/** Live cartography UI config and sample scope, passed together when the analytic is enabled. */
export type StellarCartographyMapContext = {
  config: StellarCartographyMapUiConfig
  analyticScope: AnalyticShellScope
}

export type CombineMapDataOptionsBase = {
  /** When set, connection routes are clipped to match the UI flare mode if the response is stale. */
  liveConnectionsParams: ConnectionsMapParams | null
  /** Extrapolate ion storm positions forward from the latest stored turn. */
  futureTurnOffset?: number
}

export function defaultStellarCartographyMapUiConfig(): StellarCartographyMapUiConfig {
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
