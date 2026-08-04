/**
 * Resolve planet id from base-map nodes (`planet.id` field or `pN` node id fallback).
 */

import type { MapNode } from '../../api/bff'

function planetIdFromPlanetField(raw: unknown): number | null {
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    return Math.trunc(raw)
  }
  if (typeof raw === 'string' && raw.trim() !== '') {
    const parsed = Number.parseInt(raw.trim(), 10)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function planetIdFromLocalMapNodeId(nodeId: string): number | null {
  const localId = nodeId.includes(':') ? nodeId.slice(nodeId.indexOf(':') + 1) : nodeId
  const match = /^p(\d+)$/.exec(localId)
  if (match != null) {
    return Number.parseInt(match[1]!, 10)
  }
  return null
}

/** Planet id from a map node `planet.id` or `pN` suffix in `node.id`. */
export function planetIdFromMapNode(node: MapNode): number | null {
  const fromPlanet = planetIdFromPlanetField(node.planet?.id)
  if (fromPlanet != null) return fromPlanet
  return planetIdFromLocalMapNodeId(node.id)
}

/** Planet id from a map node id, searching `nodes` when the node record is available. */
export function planetIdFromNodeId(
  nodeId: string,
  nodes: readonly MapNode[]
): number | null {
  const node = nodes.find((row) => row.id === nodeId)
  if (node != null) return planetIdFromMapNode(node)
  return planetIdFromLocalMapNodeId(nodeId)
}
