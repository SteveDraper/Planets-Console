import type {
  CombinedMapData,
  ConnectionsMapParams,
  MapDataResponse,
  MapEdge,
} from '../api/bff'
import { routeWaypointsFromMap } from './connections/mapLayer'
import { applyFutureIonStormOverlayPositions } from '../lib/cartography/futureTurnIonStorms'
import {
  mapLayerMergerFor,
  type MapLayerMergeContext,
} from './mapAnalyticRegistry'
import { BASE_MAP_ANALYTIC_ID } from './mapAnalyticIds'

export type CombineMapDataOptionsBase = {
  /** When set, connection routes are clipped to match the UI flare mode if the response is stale. */
  liveConnectionsParams: ConnectionsMapParams | null
  /** Extrapolate ion storm positions forward from the latest stored turn. */
  futureTurnOffset?: number
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
