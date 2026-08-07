/**
 * Pane-space hit-test for fleet location rings (no DOM pointer capture).
 * Same event model as region overlays: listen on the React Flow pane, test geometry.
 */

import { flowCenterFromMapNode, safeZoomScale } from '../../lib/mapFlowGeometry'
import type { FleetLocationRingStack } from './fleetLocationRings'

/** Extra screen px beyond outer radius for easier hover. */
export const FLEET_LOCATION_RING_HIT_PADDING_PX = 4

/**
 * Closest stack whose annulus hit disk covers the pane point, or null.
 * ``paneX`` / ``paneY`` are CSS pixels relative to the React Flow pane origin.
 */
export function findFleetLocationRingStackAtPanePoint(
  stacks: readonly FleetLocationRingStack[],
  paneX: number,
  paneY: number,
  transform: [number, number, number],
  hitPaddingPx: number = FLEET_LOCATION_RING_HIT_PADDING_PX
): FleetLocationRingStack | null {
  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  let best: FleetLocationRingStack | null = null
  let bestDistSq = Infinity
  for (const stack of stacks) {
    const { cx, cy } = flowCenterFromMapNode({ x: stack.x, y: stack.y })
    const stackPaneX = cx * scale + tx
    const stackPaneY = cy * scale + ty
    const dx = paneX - stackPaneX
    const dy = paneY - stackPaneY
    const distSq = dx * dx + dy * dy
    const hitR = stack.diameterPx / 2 + hitPaddingPx
    if (distSq <= hitR * hitR && distSq < bestDistSq) {
      best = stack
      bestDistSq = distSq
    }
  }
  return best
}
