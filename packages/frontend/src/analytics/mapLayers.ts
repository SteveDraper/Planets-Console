import type {
  CombinedMapData,
  ConnectionsMapParams,
  MapDataResponse,
  MapEdge,
} from '../api/bff'
import { routeWaypointsFromMap } from './connections/mapLayer'
import {
  mapLayerMergerFor,
  type MapLayerMergeContext,
} from './mapAnalyticRegistry'
import { BASE_MAP_ANALYTIC_ID } from './mapAnalyticIds'

export type CombineMapDataOptionsBase = {
  /** When set, connection routes are clipped to match the UI flare mode if the response is stale. */
  liveConnectionsParams: ConnectionsMapParams | null
}

export function combineMapData(
  analyticIds: readonly string[],
  results: { data?: MapDataResponse }[],
  options: CombineMapDataOptionsBase,
  futureTurnOffset = 0
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
    futureTurnOffset,
  }
  results.forEach((result, idx) => {
    const data = result.data
    const slotId = analyticIds[idx] ?? ''
    if (!data || slotId === '') return
    mapLayerMergerFor(slotId)(data, context, options, slotId)
  })
  return {
    nodes,
    edges,
    routeWaypoints: routeWaypointsFromMap(context.waypointsByKey),
    overlayCircles: context.overlayCircles,
    wormholeUnknownEntrances,
    nuIonStorms: context.nuIonStorms,
  }
}
