import type { CombinedMapData, MapEdge } from '../../api/bff'
import { applyFutureIonStormOverlayPositions } from '../../lib/cartography/futureTurnIonStorms'
import type {
  CartographyMapFrameParts,
  CartographyVisibilityPolicy,
} from './cartographyVisibilityPolicy'

export {
  collectWormholeEndpoints,
  withoutCartographyNodes,
} from './cartographyWormholeFrame'

/** Static display frame: visibility-filtered frame parts plus display-ready overlay circles. */
export type CartographyMapFrame = CartographyMapFrameParts & {
  overlayCircles: CombinedMapData['overlayCircles']
}

function overlayCirclesForDisplay(
  data: CombinedMapData,
  policy: CartographyVisibilityPolicy,
  futureTurnOffset: number
): CombinedMapData['overlayCircles'] {
  const filtered = policy.overlayCircles(data.overlayCircles)
  if (futureTurnOffset <= 0) {
    return filtered
  }
  return applyFutureIonStormOverlayPositions(filtered, futureTurnOffset)
}

/**
 * Static cartography map frame from combined map data and the resolved visibility policy.
 * Applies visibility filtering and optional future-turn ion storm extrapolation at display time.
 */
export function buildCartographyMapFrame(
  data: CombinedMapData,
  policy: CartographyVisibilityPolicy,
  futureTurnOffset = 0
): CartographyMapFrame {
  return {
    ...policy.mapFrameParts(data),
    overlayCircles: overlayCirclesForDisplay(data, policy, futureTurnOffset),
  }
}

/** Applies visibility policy and optional wormhole hover reveal to a map frame's edges. */
export function cartographyDisplayEdges(
  frame: CartographyMapFrame,
  policy: CartographyVisibilityPolicy,
  wormholeLineRevealKey: string | null = null
): MapEdge[] {
  return policy.mapEdges(frame.baseEdges, wormholeLineRevealKey)
}
