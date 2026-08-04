/**
 * Planet id → map coordinates from base-map nodes.
 */

import type { MapNode } from '../../api/bff'
import { planetIdFromMapNode } from './planetIdFromMapNode'

export function planetPositionsFromBaseMap(
  nodes: readonly MapNode[]
): Map<number, { x: number; y: number }> {
  const out = new Map<number, { x: number; y: number }>()
  for (const node of nodes) {
    const planetId = planetIdFromMapNode(node)
    if (planetId == null) continue
    out.set(planetId, { x: Number(node.x), y: Number(node.y) })
  }
  return out
}
