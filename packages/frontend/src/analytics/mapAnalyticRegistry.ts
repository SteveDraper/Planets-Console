import { fetchAnalyticMap } from '../api/bff'
import type {
  AnalyticShellScope,
  CombinedMapData,
  MapDataResponse,
  MapEdge,
} from '../api/bff'
import type { ConnectionsMapParams } from './connections/api'
import { connectionsMapAnalytic } from './connections/mapAnalytic'
import {
  BASE_MAP_ANALYTIC_ID,
  CONNECTIONS_ANALYTIC_ID,
  FLEET_ANALYTIC_ID,
  STELLAR_CARTOGRAPHY_ANALYTIC_ID,
} from './mapAnalyticIds'
import { stellarCartographyMapAnalytic } from './stellar-cartography/mapAnalytic'
import { fleetMapAnalytic } from './fleet/mapAnalytic'
import type { CombineMapDataOptionsBase } from './mapLayers'

export type MapAnalyticQueryContext = {
  analyticScope: AnalyticShellScope | null
  analyticFetchEnabled: boolean
  connectionsMapParams: ConnectionsMapParams
}

export type MapAnalyticQuerySpec = {
  queryKey: readonly unknown[]
  queryFn: () => Promise<MapDataResponse>
  enabled: boolean
}

export type MapLayerMergeContext = {
  baseMapAnalyticId: string | null
  nodes: CombinedMapData['nodes']
  edges: MapEdge[]
  overlayCircles: CombinedMapData['overlayCircles']
  wormholeUnknownEntrances: CombinedMapData['wormholeUnknownEntrances']
  waypointsByKey: Map<string, { x: number; y: number }>
  nuIonStorms: boolean | undefined
}

export type MapLayerMerger = (
  data: MapDataResponse,
  context: MapLayerMergeContext,
  options: CombineMapDataOptionsBase,
  prefix: string
) => void

/**
 * Per map-capable analytic: optional parametric query spec plus merge into combined map data.
 * Register new analytics here (not in separate query and merge registries).
 */
export type MapAnalyticRegistration = {
  buildQuerySpec?: (context: MapAnalyticQueryContext) => MapAnalyticQuerySpec
  mergeLayer: MapLayerMerger
}

function prefixMapNodes(
  data: MapDataResponse,
  nodes: CombinedMapData['nodes'],
  prefix: string
): void {
  data.nodes.forEach((n) => {
    const base = {
      id: `${prefix}:${n.id}`,
      label: n.label,
      x: n.x,
      y: n.y,
    }
    const node: CombinedMapData['nodes'][number] = { ...base }
    if (n.planet != null) {
      node.planet = { ...n.planet }
      node.ownerName = n.ownerName ?? null
    }
    if (n.normalWellCells != null) {
      node.normalWellCells = n.normalWellCells
    }
    nodes.push(node)
  })
}

function prefixMapEdges(data: MapDataResponse, edges: MapEdge[], prefix: string): void {
  data.edges.forEach((e) => {
    const edge: MapEdge = {
      source: `${prefix}:${e.source}`,
      target: `${prefix}:${e.target}`,
    }
    if (e.viaFlare) edge.viaFlare = true
    edges.push(edge)
  })
}

/** Prefix nodes and edges with the analytic slot id (base map and unknown analytics). */
export const defaultMapLayerMerger: MapLayerMerger = (data, context, _options, prefix) => {
  prefixMapNodes(data, context.nodes, prefix)
  prefixMapEdges(data, context.edges, prefix)
}

export const defaultMapAnalyticRegistration: MapAnalyticRegistration = {
  mergeLayer: defaultMapLayerMerger,
}

const mapAnalyticRegistry: Record<string, MapAnalyticRegistration> = {
  [BASE_MAP_ANALYTIC_ID]: defaultMapAnalyticRegistration,
  [CONNECTIONS_ANALYTIC_ID]: connectionsMapAnalytic,
  [STELLAR_CARTOGRAPHY_ANALYTIC_ID]: stellarCartographyMapAnalytic,
  [FLEET_ANALYTIC_ID]: fleetMapAnalytic,
}

/** Canonical map analytic ids with explicit registry entries. */
export const REGISTERED_MAP_ANALYTIC_IDS = [
  BASE_MAP_ANALYTIC_ID,
  CONNECTIONS_ANALYTIC_ID,
  STELLAR_CARTOGRAPHY_ANALYTIC_ID,
  FLEET_ANALYTIC_ID,
] as const satisfies readonly string[]

export type RegisteredMapAnalyticId = (typeof REGISTERED_MAP_ANALYTIC_IDS)[number]

export function isRegisteredMapAnalytic(analyticId: string): analyticId is RegisteredMapAnalyticId {
  return (REGISTERED_MAP_ANALYTIC_IDS as readonly string[]).includes(analyticId)
}

/**
 * Returns the registration for a map analytic id.
 * Throws when the id is not explicitly registered.
 */
export function mapAnalyticRegistrationFor(analyticId: string): MapAnalyticRegistration {
  const registration = mapAnalyticRegistry[analyticId]
  if (registration == null) {
    throw new Error(`Unregistered map analytic: ${analyticId}`)
  }
  return registration
}

export function mapLayerMergerFor(analyticId: string): MapLayerMerger {
  return mapAnalyticRegistrationFor(analyticId).mergeLayer
}

export function defaultMapAnalyticQuerySpec(
  analyticId: string,
  context: MapAnalyticQueryContext
): MapAnalyticQuerySpec {
  return {
    // 'planet-v2' namespaces the cache to the current planet-map wire shape; bump it when that shape changes.
    queryKey: ['analytic', analyticId, 'map', context.analyticScope, 'planet-v2'] as const,
    queryFn: () => {
      if (context.analyticScope == null) {
        throw new Error('Map analytic query requires analytic scope')
      }
      return fetchAnalyticMap(analyticId, context.analyticScope, undefined)
    },
    enabled: context.analyticFetchEnabled && context.analyticScope != null,
  }
}

export function mapAnalyticQuerySpecFor(
  analyticId: string,
  context: MapAnalyticQueryContext
): MapAnalyticQuerySpec {
  const registration = mapAnalyticRegistrationFor(analyticId)
  return registration.buildQuerySpec?.(context) ?? defaultMapAnalyticQuerySpec(analyticId, context)
}
