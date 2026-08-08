/**
 * Fleet descriptive hit-test for the **map interaction surface**.
 */

import type { FleetLocationRingStack } from '../../analytics/fleet/fleetLocationRings'
import { findFleetLocationRingStackAtPanePoint } from '../../analytics/fleet/fleetLocationRingHitTest'
import { flowCenterFromMapNode } from '../../lib/mapFlowGeometry'
import type { MapHitContext } from '../mapInteractionContributorTypes'

export type FleetHitResult = {
  stack: FleetLocationRingStack
  flowX: number
  flowY: number
}

export function hitTestFleetAtPointer(
  hit: MapHitContext,
  stacks: readonly FleetLocationRingStack[]
): FleetHitResult | null {
  if (hit.domNode == null || hit.transform == null || stacks.length === 0) return null
  const rect = hit.domNode.getBoundingClientRect()
  const paneX = hit.clientPos.x - rect.left
  const paneY = hit.clientPos.y - rect.top
  const stack = findFleetLocationRingStackAtPanePoint(
    stacks,
    paneX,
    paneY,
    hit.transform
  )
  if (stack == null) return null
  const { cx, cy } = flowCenterFromMapNode({ x: stack.x, y: stack.y })
  return { stack, flowX: cx, flowY: cy }
}
