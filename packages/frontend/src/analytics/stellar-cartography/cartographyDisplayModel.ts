import type { CombinedMapData, MapEdge } from '../../api/bff'
import { STELLAR_CARTOGRAPHY_NODE_ID_PREFIX } from '../mapAnalyticIds'
import {
  buildWormholeEndpointHoverIndex,
  type WormholeEndpointHoverInfo,
} from '../../lib/wormholeEndpointHover'
import type { StellarCartographyMapContext } from './mapUiConfig'
import type { CartographyVisibilityPolicy } from './cartographyVisibilityPolicy'
import { cartographyFramePolicy } from './cartographyVisibilityPolicy'

/** Static display frame from combined map data; mount cartography UI when {@link StellarCartographyMapContext} is passed. */
export type CartographyMapFrame = {
  nodes: CombinedMapData['nodes']
  /** Map edges before hover-sensitive wormhole line filtering. */
  baseEdges: MapEdge[]
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

/**
 * Static cartography map frame from combined map data and UI config.
 * Does not apply hover-sensitive wormhole line filtering; use {@link cartographyMapEdges} for that.
 */
export function buildCartographyMapFrame(
  data: CombinedMapData,
  cartography: StellarCartographyMapContext | undefined
): CartographyMapFrame {
  const policy = cartographyFramePolicy(cartography)
  const overlayCircles = policy.overlayCircles(data.overlayCircles)
  const wormholesShown = policy.areWormholesShown()
  const nodes = wormholesShown ? data.nodes : withoutCartographyNodes(data.nodes)
  const baseEdges = wormholesShown ? [...data.edges] : policy.mapEdges(data.edges, null)

  return {
    nodes,
    baseEdges,
    overlayCircles,
    wormholeUnknownEntrances: wormholesShown ? data.wormholeUnknownEntrances : [],
    wormholeEndpoints: wormholesShown
      ? collectWormholeEndpoints(nodes, data.wormholeUnknownEntrances)
      : [],
    wormholeEndpointHoverByCell: wormholesShown
      ? buildWormholeEndpointHoverIndex(data.edges, data.wormholeUnknownEntrances)
      : new Map(),
  }
}

/** Applies visibility policy and optional wormhole hover reveal to a map frame's edges. */
export function cartographyMapEdges(
  frame: CartographyMapFrame,
  policy: CartographyVisibilityPolicy | undefined,
  wormholeLineRevealKey: string | null = null
): MapEdge[] {
  if (policy == null) {
    return frame.baseEdges
  }
  return policy.mapEdges(frame.baseEdges, wormholeLineRevealKey)
}
