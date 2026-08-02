import type {
  HomeworldMapMarkerDisplay,
  MapDataResponse,
  MapNode,
} from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { normalizeMapRegionOverlays } from '../../api/normalizeMapRegionOverlay'
import type { MapAnalyticQueryContext, MapAnalyticRegistration } from '../mapAnalyticRegistry'
import { HOMEWORLD_LOCATOR_ANALYTIC_ID } from './constants'
import { fetchHomeworldLocatorMap } from './api'
import type { HomeworldLocatorPayload, HomeworldMapMarker } from './wireSchema'

export type { HomeworldMapMarkerDisplay }

function planetIdFromMapNode(node: MapNode): number | null {
  const raw = node.planet?.id
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    return Math.trunc(raw)
  }
  if (typeof raw === 'string' && raw.trim() !== '') {
    const parsed = Number.parseInt(raw.trim(), 10)
    if (Number.isFinite(parsed)) return parsed
  }
  const localId = node.id.includes(':') ? node.id.slice(node.id.indexOf(':') + 1) : node.id
  const match = /^p(\d+)$/.exec(localId)
  if (match != null) {
    return Number.parseInt(match[1]!, 10)
  }
  return null
}

/** Resolve homeworld markers onto base-map planet coordinates. */
export function resolveHomeworldMarkerDisplays(
  markers: readonly HomeworldMapMarker[],
  nodes: readonly MapNode[],
  baseMapAnalyticId: string | null
): HomeworldMapMarkerDisplay[] {
  if (baseMapAnalyticId == null || markers.length === 0) return []
  const byPlanetId = new Map<number, MapNode>()
  const prefix = `${baseMapAnalyticId}:`
  for (const node of nodes) {
    if (!node.id.startsWith(prefix)) continue
    const planetId = planetIdFromMapNode(node)
    if (planetId == null) continue
    byPlanetId.set(planetId, node)
  }
  const out: HomeworldMapMarkerDisplay[] = []
  for (const marker of markers) {
    const node = byPlanetId.get(marker.planetId)
    if (node == null) continue
    out.push({
      planetId: marker.planetId,
      x: Number(node.x),
      y: Number(node.y),
      confidenceTier: marker.confidenceTier,
      perspective: marker.perspective,
      attribution: marker.attribution,
      isMostProbable: marker.isMostProbable ?? false,
    })
  }
  return out
}

export function homeworldLocatorMapQueryKey(analyticScope: MapAnalyticQueryContext['analyticScope']) {
  // Bump when overlay wire annotations change (e.g. structured hover facts) so
  // cached map payloads without those fields cannot keep hover/display broken.
  return ['analytic', HOMEWORLD_LOCATOR_ANALYTIC_ID, 'map', analyticScope, 'sectors-v4'] as const
}

function markersFromMapResponse(data: MapDataResponse): HomeworldMapMarker[] {
  return data.homeworldMarkers ?? []
}

function regionOverlaysFromPayload(payload: HomeworldLocatorPayload): MapRegionOverlay[] {
  return normalizeMapRegionOverlays(payload.regionOverlays ?? [])
}

/**
 * Homeworld locator: fetch candidate markers and sector ``regionOverlays``,
 * then merge into combined map data. Display-mode filtering is render-time.
 */
export const homeworldLocatorMapAnalytic: MapAnalyticRegistration = {
  buildQuerySpec(context: MapAnalyticQueryContext) {
    return {
      queryKey: homeworldLocatorMapQueryKey(context.analyticScope),
      queryFn: async (): Promise<MapDataResponse> => {
        if (context.analyticScope == null) {
          throw new Error('Homeworld locator map query requires analytic scope')
        }
        const payload = await fetchHomeworldLocatorMap(context.analyticScope)
        const available = payload.available
        return {
          analyticId: HOMEWORLD_LOCATOR_ANALYTIC_ID,
          nodes: [],
          edges: [],
          homeworldMarkers: available ? (payload.markers ?? []) : [],
          regionOverlays: available ? regionOverlaysFromPayload(payload) : [],
          // Only surface degraded metadata when the analytic is active (matches table tile).
          baselineDegraded: available ? payload.baselineDegraded : false,
          baselineTurn: available ? (payload.baselineTurn ?? null) : null,
        }
      },
      enabled: context.analyticFetchEnabled && context.analyticScope != null,
    }
  },
  mergeLayer(data, context) {
    if (data.baselineDegraded != null) {
      context.baselineDegraded = data.baselineDegraded
    }
    if (data.baselineTurn !== undefined) {
      context.baselineTurn = data.baselineTurn
    }
    const overlays = data.regionOverlays
    if (overlays != null && overlays.length > 0) {
      context.regionOverlays.push(...overlays)
    }
    const markers = markersFromMapResponse(data)
    if (markers.length === 0) return
    const resolved = resolveHomeworldMarkerDisplays(
      markers,
      context.nodes,
      context.baseMapAnalyticId
    )
    context.homeworldMarkers.push(...resolved)
  },
}
