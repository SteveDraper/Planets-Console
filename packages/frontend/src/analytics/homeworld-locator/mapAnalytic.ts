import type {
  HomeworldMapMarkerDisplay,
  MapDataResponse,
  MapNode,
} from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { normalizeMapRegionOverlays } from '../../api/normalizeMapRegionOverlay'
import type {
  MapAnalyticQueryContext,
  MapAnalyticQuerySpec,
  MapAnalyticRegistration,
} from '../mapAnalyticRegistry'
import { HOMEWORLD_LOCATOR_ANALYTIC_ID } from './constants'
import { fetchHomeworldLocatorMap } from './api'
import { planetIdFromMapNode } from './planetIdFromMapNode'
import type { HomeworldLocatorPayload, HomeworldMapMarker } from './wireSchema'

export type { HomeworldMapMarkerDisplay }

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
      assertedCue: marker.assertedCue ?? false,
      locationAsserted: marker.locationAsserted ?? false,
      isMostProbable: marker.isMostProbable ?? false,
    })
  }
  return out
}

export function homeworldLocatorMapQueryKey(analyticScope: MapAnalyticQueryContext['analyticScope']) {
  // Bump when marker/overlay wire annotations change so stale caches cannot hide cues.
  return ['analytic', HOMEWORLD_LOCATOR_ANALYTIC_ID, 'map', analyticScope, 'sectors-v7'] as const
}

function markersFromMapResponse(data: MapDataResponse): HomeworldMapMarker[] {
  return data.homeworldMarkers ?? []
}

function regionOverlaysFromPayload(payload: HomeworldLocatorPayload): MapRegionOverlay[] {
  return normalizeMapRegionOverlays(payload.regionOverlays ?? [])
}

/**
 * Map-layer queryFn for the homeworld locator TanStack cache entry.
 * Always return a full ``MapDataResponse`` (markers + overlays); a partial write
 * under ``homeworldLocatorMapQueryKey`` would blank map cues for other observers.
 */
export async function fetchHomeworldLocatorMapDataResponse(
  analyticScope: NonNullable<MapAnalyticQueryContext['analyticScope']>
): Promise<MapDataResponse> {
  const payload = await fetchHomeworldLocatorMap(analyticScope)
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
}

/**
 * Sole owner of the homeworld map-layer query key + queryFn + enabled flag.
 * Map registration and ``useHomeworldLocatorMapOverlays`` both use this so panel
 * and map share one TanStack cache entry (same pattern as base-map positions).
 */
export function homeworldLocatorMapQuerySpec(
  analyticScope: MapAnalyticQueryContext['analyticScope'],
  analyticFetchEnabled: boolean
): MapAnalyticQuerySpec {
  return {
    queryKey: homeworldLocatorMapQueryKey(analyticScope),
    queryFn: async (): Promise<MapDataResponse> => {
      if (analyticScope == null) {
        throw new Error('Homeworld locator map query requires analytic scope')
      }
      return fetchHomeworldLocatorMapDataResponse(analyticScope)
    },
    enabled: analyticFetchEnabled && analyticScope != null,
  }
}

/**
 * Homeworld locator: fetch candidate markers and sector ``regionOverlays``,
 * then merge into combined map data. Display-mode filtering is render-time.
 */
export const homeworldLocatorMapAnalytic: MapAnalyticRegistration = {
  buildQuerySpec(context: MapAnalyticQueryContext) {
    return homeworldLocatorMapQuerySpec(
      context.analyticScope,
      context.analyticFetchEnabled
    )
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
