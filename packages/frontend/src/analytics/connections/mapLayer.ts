import type {
  CombinedMapData,
  IllustrativeRouteStep,
  MapDataResponse,
  MapEdge,
} from '../../api/bff'
import type { ConnectionsMapParams } from './api'

/** Game cells visited before the last hop; excludes the destination planet's arrival cell. */
function intermediateGameCellsFromIllustrative(
  steps: IllustrativeRouteStep[] | undefined
): { x: number; y: number }[] {
  if (steps == null || steps.length <= 1) return []
  const out: { x: number; y: number }[] = []
  for (let i = 0; i < steps.length - 1; i += 1) {
    const to = steps[i]?.to
    if (to == null) continue
    const x = Math.trunc(to.x)
    const y = Math.trunc(to.y)
    if (Number.isFinite(x) && Number.isFinite(y)) {
      out.push({ x, y })
    }
  }
  return out
}

export function appendConnectionsMapLayer({
  data,
  baseMapAnalyticId,
  liveConnectionsParams,
  edges,
  waypointsByKey,
}: {
  data: MapDataResponse
  baseMapAnalyticId: string
  liveConnectionsParams: ConnectionsMapParams | null
  edges: MapEdge[]
  waypointsByKey: Map<string, { x: number; y: number }>
}): void {
  if (data.routes == null || data.routes.length === 0) return
  let routesToDraw = data.routes
  if (liveConnectionsParams != null) {
    if (liveConnectionsParams.flareMode === 'only') {
      routesToDraw = routesToDraw.filter((r) => r.viaFlare === true)
    } else if (liveConnectionsParams.flareMode === 'off') {
      routesToDraw = routesToDraw.filter((r) => r.viaFlare !== true)
    }
  }
  for (const r of routesToDraw) {
    const intermediates =
      r.viaFlare === true && r.illustrativeRoute
        ? intermediateGameCellsFromIllustrative(r.illustrativeRoute)
        : []
    const edge: MapEdge = {
      source: `${baseMapAnalyticId}:p${r.fromPlanetId}`,
      target: `${baseMapAnalyticId}:p${r.toPlanetId}`,
      viaFlare: r.viaFlare === true,
    }
    if (intermediates.length > 0) {
      edge.waypointsInGame = intermediates.map((c) => ({ x: c.x, y: c.y }))
    }
    edges.push(edge)
    if (r.viaFlare === true && r.illustrativeRoute) {
      for (const c of intermediates) {
        const k = `${c.x},${c.y}`
        if (!waypointsByKey.has(k)) {
          waypointsByKey.set(k, c)
        }
      }
    }
  }
}

export function routeWaypointsFromMap(
  waypointsByKey: Map<string, { x: number; y: number }>
): CombinedMapData['routeWaypoints'] {
  return [...waypointsByKey.values()].map((c) => ({
    id: `wp:${c.x},${c.y}`,
    gx: c.x,
    gy: c.y,
  }))
}
