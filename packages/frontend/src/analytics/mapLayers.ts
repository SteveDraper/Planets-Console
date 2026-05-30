import type { CombinedMapData, ConnectionsMapParams, MapDataResponse, MapEdge } from '../api/bff'
import type {
  CartographyLayerVisibility,
  StellarCartographySettingsGates,
} from './stellar-cartography/layers'
import type { WormholeDisplayMode } from './stellar-cartography/wormholeDisplayMode'
import type { ClusterOutlineDisplayMode } from './stellar-cartography/clusterOutlineDisplayMode'
import { appendStellarCartographyMapLayer } from './stellar-cartography/mapLayer'
import { appendConnectionsMapLayer, routeWaypointsFromMap } from './connections/mapLayer'

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
  stellarCartography?: StellarCartographyMapMergeOptions
}

export type CombineMapDataOptionsWithStellarCartography = CombineMapDataOptionsBase & {
  stellarCartography: StellarCartographyMapMergeOptions
}

type MapLayerMergeContext = {
  baseMapAnalyticId: string | null
  nodes: CombinedMapData['nodes']
  edges: MapEdge[]
  overlayCircles: CombinedMapData['overlayCircles']
  wormholeUnknownEntrances: CombinedMapData['wormholeUnknownEntrances']
  waypointsByKey: Map<string, { x: number; y: number }>
  nuIonStorms: boolean | undefined
}

type MapLayerMerger = (
  data: MapDataResponse,
  context: MapLayerMergeContext,
  options: CombineMapDataOptionsBase,
  prefix: string
) => void

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
      node.planet = n.planet
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
const defaultMapLayerMerger: MapLayerMerger = (data, context, _options, prefix) => {
  prefixMapNodes(data, context.nodes, prefix)
  prefixMapEdges(data, context.edges, prefix)
}

const mapLayerMergeRegistry: Record<string, MapLayerMerger> = {
  'base-map': defaultMapLayerMerger,
  connections: (data, context, options) => {
    if (context.baseMapAnalyticId == null) return
    appendConnectionsMapLayer({
      data,
      baseMapAnalyticId: context.baseMapAnalyticId,
      liveConnectionsParams: options.liveConnectionsParams,
      edges: context.edges,
      waypointsByKey: context.waypointsByKey,
    })
  },
  'stellar-cartography': (data, context, options) => {
    const stellarCartography = options.stellarCartography
    if (stellarCartography == null) {
      throw new Error('Stellar Cartography map merge requires stellarCartography options')
    }
    if (data.meta?.nuIonStorms != null) {
      context.nuIonStorms = data.meta.nuIonStorms
    }
    appendStellarCartographyMapLayer({
      data,
      nodes: context.nodes,
      edges: context.edges,
      overlayCircles: context.overlayCircles,
      wormholeUnknownEntrances: context.wormholeUnknownEntrances,
      layerVisibility: stellarCartography.layerVisibility,
      settingsGates: stellarCartography.settingsGates,
      wormholeDisplayMode: stellarCartography.wormholeDisplayMode,
      starClusterDisplayMode: stellarCartography.starClusterDisplayMode,
      neutronClusterDisplayMode: stellarCartography.neutronClusterDisplayMode,
    })
  },
}

function mapLayerMergerFor(analyticId: string): MapLayerMerger {
  return mapLayerMergeRegistry[analyticId] ?? defaultMapLayerMerger
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
  return {
    nodes,
    edges,
    routeWaypoints: routeWaypointsFromMap(context.waypointsByKey),
    overlayCircles,
    wormholeUnknownEntrances,
    nuIonStorms: context.nuIonStorms,
  }
}
