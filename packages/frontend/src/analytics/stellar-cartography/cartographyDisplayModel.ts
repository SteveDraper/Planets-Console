import type { CombinedMapData, MapEdge } from '../../api/bff'
import type { WormholeEndpointHoverInfo } from '../../lib/wormholeEndpointHover'
import type { StellarCartographyMapContext } from './mapUiConfig'
import type { CartographyVisibilityPolicy } from './cartographyVisibilityPolicy'
import { cartographyFramePolicy } from './cartographyVisibilityPolicy'

export {
  collectWormholeEndpoints,
  withoutCartographyNodes,
} from './cartographyWormholeFrame'

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

/**
 * Static cartography map frame from combined map data and UI config.
 * Does not apply hover-sensitive wormhole line filtering; use {@link cartographyMapEdges} for that.
 */
export function buildCartographyMapFrame(
  data: CombinedMapData,
  cartography: StellarCartographyMapContext | undefined
): CartographyMapFrame {
  const policy = cartographyFramePolicy(cartography)
  return {
    ...policy.mapFrameParts(data),
    overlayCircles: policy.overlayCircles(data.overlayCircles),
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
