import type { CombinedMapData, MapEdge } from '../../api/bff'
import { STELLAR_CARTOGRAPHY_NODE_ID_PREFIX } from '../mapAnalyticIds'
import {
  buildWormholeEndpointHoverIndex,
  type WormholeEndpointHoverInfo,
} from '../../lib/wormholeEndpointHover'
import type { StellarCartographyMapContext } from './mapUiConfig'
import {
  areCartographyWormholesShown,
  filterCartographyOverlayCircles,
  filterWormholeEdgesForCartographyConfig,
} from './overlayDisplayFilter'

export type CartographyDisplayModel = {
  /** When false, cartography overlay and hover UI should not mount. */
  cartographyEnabled: boolean
  nodes: CombinedMapData['nodes']
  edges: MapEdge[]
  overlayCircles: CombinedMapData['overlayCircles']
  wormholeUnknownEntrances: CombinedMapData['wormholeUnknownEntrances']
  wormholeEndpoints: { x: number; y: number }[]
  wormholeEndpointHoverByCell: Map<string, WormholeEndpointHoverInfo>
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

function emptyCartographyDisplayModel(
  nodes: CombinedMapData['nodes'],
  edges: MapEdge[]
): CartographyDisplayModel {
  return {
    cartographyEnabled: false,
    nodes,
    edges,
    overlayCircles: [],
    wormholeUnknownEntrances: [],
    wormholeEndpoints: [],
    wormholeEndpointHoverByCell: new Map(),
  }
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
  if (cartography == null) {
    return emptyCartographyDisplayModel(
      withoutCartographyNodes(data.nodes),
      withoutWormholeEdges(data.edges)
    )
  }

  const { config } = cartography
  const overlayCircles = filterCartographyOverlayCircles(data.overlayCircles, config)
  const wormholesShown = areCartographyWormholesShown(config)

  if (!wormholesShown) {
    const nodes = withoutCartographyNodes(data.nodes)
    return {
      cartographyEnabled: true,
      nodes,
      edges: withoutWormholeEdges(data.edges),
      overlayCircles,
      wormholeUnknownEntrances: [],
      wormholeEndpoints: [],
      wormholeEndpointHoverByCell: new Map(),
    }
  }

  const nodes = data.nodes
  const wormholeUnknownEntrances = data.wormholeUnknownEntrances
  const edges = filterWormholeEdgesForCartographyConfig(
    data.edges,
    config,
    wormholeLineRevealKey
  )
  const wormholeEndpointHoverByCell = buildWormholeEndpointHoverIndex(
    data.edges,
    wormholeUnknownEntrances
  )
  const wormholeEndpoints = collectWormholeEndpoints(nodes, wormholeUnknownEntrances)

  return {
    cartographyEnabled: true,
    nodes,
    edges,
    overlayCircles,
    wormholeUnknownEntrances,
    wormholeEndpoints,
    wormholeEndpointHoverByCell,
  }
}
