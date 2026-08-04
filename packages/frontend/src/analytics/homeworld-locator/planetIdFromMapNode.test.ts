import { describe, expect, it } from 'vitest'
import type { MapNode } from '../../api/bff'
import { planetIdFromMapNode, planetIdFromNodeId } from './planetIdFromMapNode'

function mapNode(id: string, planetId?: number | string): MapNode {
  return {
    id,
    label: id,
    x: 0,
    y: 0,
    planet: planetId != null ? { id: planetId } : undefined,
  }
}

describe('planetIdFromMapNode', () => {
  it('reads numeric planet.id', () => {
    expect(planetIdFromMapNode(mapNode('base:p12', 12))).toBe(12)
  })

  it('reads string planet.id', () => {
    expect(planetIdFromMapNode(mapNode('base:p12', '12'))).toBe(12)
  })

  it('falls back to pN suffix in node.id', () => {
    expect(planetIdFromMapNode(mapNode('base:p44'))).toBe(44)
  })

  it('returns null when no planet id is available', () => {
    expect(planetIdFromMapNode(mapNode('base:ship-1'))).toBeNull()
  })
})

describe('planetIdFromNodeId', () => {
  it('resolves from a matching node record', () => {
    const nodes = [mapNode('base:p9', 9)]
    expect(planetIdFromNodeId('base:p9', nodes)).toBe(9)
  })

  it('parses nodeId when the node record is missing', () => {
    expect(planetIdFromNodeId('base:p7', [])).toBe(7)
  })
})
