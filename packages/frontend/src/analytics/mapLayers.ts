import type { CombinedMapData, ConnectionsMapParams, MapDataResponse, MapEdge } from '../api/bff'
import type {
  CartographyLayerVisibility,
  StellarCartographySettingsGates,
} from './stellar-cartography/layers'
import type { WormholeDisplayMode } from './stellar-cartography/wormholeDisplayMode'
import { appendStellarCartographyMapLayer } from './stellar-cartography/mapLayer'
import { appendConnectionsMapLayer, routeWaypointsFromMap } from './connections/mapLayer'

export type CombineMapDataOptions = {
  /** When set, connection routes are clipped to match the UI flare mode if the response is stale. */
  liveConnectionsParams: ConnectionsMapParams | null
  cartographyLayerVisibility?: CartographyLayerVisibility
  cartographySettingsGates?: StellarCartographySettingsGates
  wormholeDisplayMode?: WormholeDisplayMode
}

export function combineMapData(
  analyticIds: string[],
  results: { data?: MapDataResponse }[],
  options: CombineMapDataOptions | ConnectionsMapParams | null
): CombinedMapData {
  const liveConnectionsParams =
    options != null && 'liveConnectionsParams' in options
      ? options.liveConnectionsParams
      : options
  const cartographyLayerVisibility =
    options != null && 'cartographyLayerVisibility' in options
      ? options.cartographyLayerVisibility
      : undefined
  const cartographySettingsGates =
    options != null && 'cartographySettingsGates' in options
      ? options.cartographySettingsGates
      : undefined
  const wormholeDisplayMode =
    options != null && 'wormholeDisplayMode' in options
      ? options.wormholeDisplayMode
      : undefined

  const baseMapAnalyticId = analyticIds.find((id) => id === 'base-map') ?? null
  const nodes: CombinedMapData['nodes'] = []
  const edges: MapEdge[] = []
  const overlayCircles: CombinedMapData['overlayCircles'] = []
  const wormholeUnknownEntrances: CombinedMapData['wormholeUnknownEntrances'] = []
  let nuIonStorms: boolean | undefined
  const waypointsByKey = new Map<string, { x: number; y: number }>()
  results.forEach((result, idx) => {
    const data = result.data
    const prefix = analyticIds[idx] ?? ''
    if (!data) return
    if (data.analyticId !== 'stellar-cartography') {
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
    if (data.analyticId !== 'connections' && data.analyticId !== 'stellar-cartography') {
      data.edges.forEach((e) => {
        const edge: MapEdge = {
          source: `${prefix}:${e.source}`,
          target: `${prefix}:${e.target}`,
        }
        if (e.viaFlare) edge.viaFlare = true
        edges.push(edge)
      })
    }
    if (data.analyticId === 'connections' && baseMapAnalyticId != null) {
      appendConnectionsMapLayer({
        data,
        baseMapAnalyticId,
        liveConnectionsParams,
        edges,
        waypointsByKey,
      })
    }
    if (
      data.analyticId === 'stellar-cartography' &&
      cartographyLayerVisibility != null &&
      cartographySettingsGates != null &&
      wormholeDisplayMode != null
    ) {
      if (data.meta?.nuIonStorms != null) {
        nuIonStorms = data.meta.nuIonStorms
      }
      appendStellarCartographyMapLayer({
        data,
        nodes,
        edges,
        overlayCircles,
        wormholeUnknownEntrances,
        layerVisibility: cartographyLayerVisibility,
        settingsGates: cartographySettingsGates,
        wormholeDisplayMode,
      })
    }
  })
  return {
    nodes,
    edges,
    routeWaypoints: routeWaypointsFromMap(waypointsByKey),
    overlayCircles,
    wormholeUnknownEntrances,
    nuIonStorms,
  }
}
