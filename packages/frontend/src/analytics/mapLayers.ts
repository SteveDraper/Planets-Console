import type { CombinedMapData, ConnectionsMapParams, MapDataResponse, MapEdge } from '../api/bff'
import { appendConnectionsMapLayer, routeWaypointsFromMap } from './connections/mapLayer'

export function combineMapData(
  analyticIds: string[],
  results: { data?: MapDataResponse }[],
  /** When set, connection routes are clipped to match the UI flare mode if the response is stale. */
  liveConnectionsParams: ConnectionsMapParams | null
): CombinedMapData {
  const baseMapAnalyticId = analyticIds.find((id) => id === 'base-map') ?? null
  const nodes: CombinedMapData['nodes'] = []
  const edges: MapEdge[] = []
  const waypointsByKey = new Map<string, { x: number; y: number }>()
  results.forEach((result, idx) => {
    const data = result.data
    const prefix = analyticIds[idx] ?? ''
    if (!data) return
    data.nodes.forEach((n) => {
      const base = {
        id: `${prefix}:${n.id}`,
        label: n.label,
        x: n.x,
        y: n.y,
      }
      if (n.planet != null) {
        nodes.push({ ...base, planet: n.planet, ownerName: n.ownerName ?? null })
      } else {
        nodes.push(base)
      }
    })
    data.edges.forEach((e) => {
      const edge: MapEdge = {
        source: `${prefix}:${e.source}`,
        target: `${prefix}:${e.target}`,
      }
      if (e.viaFlare) edge.viaFlare = true
      edges.push(edge)
    })
    if (data.analyticId === 'connections' && baseMapAnalyticId != null) {
      appendConnectionsMapLayer({
        data,
        baseMapAnalyticId,
        liveConnectionsParams,
        edges,
        waypointsByKey,
      })
    }
  })
  return {
    nodes,
    edges,
    routeWaypoints: routeWaypointsFromMap(waypointsByKey),
  }
}
