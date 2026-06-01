import type { CombinedMapData, MapEdge } from '../../api/bff'
import { STELLAR_CARTOGRAPHY_NODE_ID_PREFIX } from '../mapAnalyticIds'
import {
  buildWormholeEndpointHoverIndex,
  type WormholeEndpointHoverInfo,
} from '../../lib/wormholeEndpointHover'
import type { StellarCartographyMapContext, StellarCartographyMapUiConfig } from './mapUiConfig'
import { cartographyVisibilityPolicy } from './cartographyVisibilityPolicy'

/** Static cartography map artifacts; wormhole line visibility is applied separately. */
export type CartographyMapFrame = {
  /** When false, cartography overlay and hover UI should not mount. */
  cartographyEnabled: boolean
  nodes: CombinedMapData['nodes']
  /** Map edges before hover-sensitive wormhole line filtering. */
  baseEdges: MapEdge[]
  overlayCircles: CombinedMapData['overlayCircles']
  wormholeUnknownEntrances: CombinedMapData['wormholeUnknownEntrances']
  wormholeEndpoints: { x: number; y: number }[]
  wormholeEndpointHoverByCell: Map<string, WormholeEndpointHoverInfo>
}

/** Full display model including edge filtering (convenience for tests and one-shot callers). */
export type CartographyDisplayModel = CartographyMapFrame & {
  edges: MapEdge[]
}

export function collectWormholeEndpoints(
  nodes: CombinedMapData['nodes'],
  unknownEntrances: CombinedMapData['wormholeUnknownEntrances']
): { x: number; y: number }[] {
  const seen = new Set<string>()
  const endpoints: { x: number; y: number }[] = []
  const add = (x: number, y: number) => {
    const key = `${x},${y}`
    if (seen.has(key)) return
    seen.add(key)
    endpoints.push({ x, y })
  }
  for (const node of nodes) {
    if (node.id.startsWith(STELLAR_CARTOGRAPHY_NODE_ID_PREFIX)) {
      add(Number(node.x), Number(node.y))
    }
  }
  for (const entrance of unknownEntrances) {
    add(entrance.x, entrance.y)
  }
  return endpoints
}

function withoutCartographyNodes(nodes: CombinedMapData['nodes']): CombinedMapData['nodes'] {
  return nodes.filter((node) => !node.id.startsWith(STELLAR_CARTOGRAPHY_NODE_ID_PREFIX))
}

function withoutWormholeEdges(edges: readonly MapEdge[]): MapEdge[] {
  return edges.filter((edge) => edge.layer !== 'wormholes')
}

function emptyCartographyMapFrame(
  nodes: CombinedMapData['nodes'],
  baseEdges: MapEdge[]
): CartographyMapFrame {
  return {
    cartographyEnabled: false,
    nodes,
    baseEdges,
    overlayCircles: [],
    wormholeUnknownEntrances: [],
    wormholeEndpoints: [],
    wormholeEndpointHoverByCell: new Map(),
  }
}

/**
 * Static cartography map frame from combined map data and UI config.
 * Does not apply hover-sensitive wormhole line filtering; use {@link cartographyMapEdges} for that.
 */
export function buildCartographyMapFrame(
  data: CombinedMapData,
  cartography: StellarCartographyMapContext | undefined
): CartographyMapFrame {
  if (cartography == null) {
    return emptyCartographyMapFrame(
      withoutCartographyNodes(data.nodes),
      withoutWormholeEdges(data.edges)
    )
  }

  const policy = cartographyVisibilityPolicy(cartography.config)
  const overlayCircles = policy.overlayCircles(data.overlayCircles)

  if (!policy.areWormholesShown()) {
    return {
      cartographyEnabled: true,
      nodes: withoutCartographyNodes(data.nodes),
      baseEdges: withoutWormholeEdges(data.edges),
      overlayCircles,
      wormholeUnknownEntrances: [],
      wormholeEndpoints: [],
      wormholeEndpointHoverByCell: new Map(),
    }
  }

  const nodes = data.nodes
  const wormholeUnknownEntrances = data.wormholeUnknownEntrances
  return {
    cartographyEnabled: true,
    nodes,
    baseEdges: [...data.edges],
    overlayCircles,
    wormholeUnknownEntrances,
    wormholeEndpoints: collectWormholeEndpoints(nodes, wormholeUnknownEntrances),
    wormholeEndpointHoverByCell: buildWormholeEndpointHoverIndex(
      data.edges,
      wormholeUnknownEntrances
    ),
  }
}

/** Applies visibility policy and optional wormhole hover reveal to a map frame's edges. */
export function cartographyMapEdges(
  frame: CartographyMapFrame,
  config: StellarCartographyMapUiConfig | undefined,
  wormholeLineRevealKey: string | null = null
): MapEdge[] {
  if (!frame.cartographyEnabled || config == null) {
    return frame.baseEdges
  }
  return cartographyVisibilityPolicy(config).mapEdges(frame.baseEdges, wormholeLineRevealKey)
}

/**
 * Single render policy for cartography map artifacts.
 * Analytic off hides all cartography content; analytic on applies layer config consistently.
 */
export function buildCartographyDisplayModel(
  data: CombinedMapData,
  cartography: StellarCartographyMapContext | undefined,
  wormholeLineRevealKey: string | null = null
): CartographyDisplayModel {
  const frame = buildCartographyMapFrame(data, cartography)
  return {
    ...frame,
    edges: cartographyMapEdges(frame, cartography?.config, wormholeLineRevealKey),
  }
}
