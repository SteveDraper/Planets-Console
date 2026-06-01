import type { CombinedMapData, MapEdge } from '../../api/bff'
import type { WormholeEndpointHoverInfo } from '../../lib/wormholeEndpointHover'
import { applyFutureIonStormOverlayPositions } from '../../lib/cartography/futureTurnIonStorms'
import type { StellarCartographyMapContext } from './mapUiConfig'
import { cartographyFramePolicy } from './cartographyVisibilityPolicy'

export {
  collectWormholeEndpoints,
  withoutCartographyNodes,
} from './cartographyWormholeFrame'

/** Static display frame from combined map data; edges omit hover-sensitive wormhole filtering. */
export type CartographyMapFrame = {
  nodes: CombinedMapData['nodes']
  /** Map edges before hover-sensitive wormhole line filtering. */
  baseEdges: MapEdge[]
  overlayCircles: CombinedMapData['overlayCircles']
  wormholeUnknownEntrances: CombinedMapData['wormholeUnknownEntrances']
  wormholeEndpoints: { x: number; y: number }[]
  wormholeEndpointHoverByCell: Map<string, WormholeEndpointHoverInfo>
}

/** Full cartography display model for map rendering (frame + hover-filtered edges). */
export type CartographyMapDisplay = CartographyMapFrame & {
  edges: MapEdge[]
}

export type BuildCartographyDisplayOptions = {
  wormholeLineRevealKey?: string | null
  futureTurnOffset?: number
}

function overlayCirclesForDisplay(
  data: CombinedMapData,
  cartography: StellarCartographyMapContext | undefined,
  futureTurnOffset: number
): CombinedMapData['overlayCircles'] {
  const policy = cartographyFramePolicy(cartography)
  const filtered = policy.overlayCircles(data.overlayCircles)
  if (futureTurnOffset <= 0) {
    return filtered
  }
  return applyFutureIonStormOverlayPositions(filtered, futureTurnOffset)
}

/**
 * Static cartography map frame from combined map data and UI config.
 * Applies visibility filtering and optional future-turn ion storm extrapolation at display time.
 */
export function buildCartographyMapFrame(
  data: CombinedMapData,
  cartography: StellarCartographyMapContext | undefined,
  futureTurnOffset = 0
): CartographyMapFrame {
  const policy = cartographyFramePolicy(cartography)
  return {
    ...policy.mapFrameParts(data),
    overlayCircles: overlayCirclesForDisplay(data, cartography, futureTurnOffset),
  }
}

/** Applies visibility policy and optional wormhole hover reveal to a map frame's edges. */
export function cartographyDisplayEdges(
  frame: CartographyMapFrame,
  cartography: StellarCartographyMapContext | undefined,
  wormholeLineRevealKey: string | null = null
): MapEdge[] {
  return cartographyFramePolicy(cartography).mapEdges(frame.baseEdges, wormholeLineRevealKey)
}

/** Builds the full cartography display model (frame + edges) from combined map data. */
export function buildCartographyDisplay(
  data: CombinedMapData,
  cartography: StellarCartographyMapContext | undefined,
  options: BuildCartographyDisplayOptions = {}
): CartographyMapDisplay {
  const futureTurnOffset = options.futureTurnOffset ?? 0
  const wormholeLineRevealKey = options.wormholeLineRevealKey ?? null
  const frame = buildCartographyMapFrame(data, cartography, futureTurnOffset)
  return {
    ...frame,
    edges: cartographyDisplayEdges(frame, cartography, wormholeLineRevealKey),
  }
}
