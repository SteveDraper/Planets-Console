import { describe, expect, it } from 'vitest'
import type { MapEdge } from '../../api/bff'
import {
  filterWormholeEdgesForDisplayMode,
  isWormholeEdgeRevealed,
  migratePersistedWormholeLayer,
} from './wormholeDisplayMode'

const wormholeEdge: MapEdge = {
  source: 'a',
  target: 'b',
  layer: 'wormholes',
  sourceGameX: 1,
  sourceGameY: 2,
  targetGameX: 9,
  targetGameY: 8,
}

describe('wormholeDisplayMode', () => {
  it('migrates legacy boolean wormholes layer to display mode', () => {
    expect(
      migratePersistedWormholeLayer({ nebulae: true, wormholes: false }, undefined)
    ).toEqual({
      layers: { nebulae: true },
      wormholeDisplayMode: 'off',
    })
    expect(
      migratePersistedWormholeLayer({ nebulae: true, wormholes: true }, undefined)
    ).toEqual({
      layers: { nebulae: true },
      wormholeDisplayMode: 'always',
    })
  })

  it('reveals wormhole edges connected to the hovered endpoint', () => {
    expect(isWormholeEdgeRevealed(wormholeEdge, '1,2')).toBe(true)
    expect(isWormholeEdgeRevealed(wormholeEdge, '9,8')).toBe(true)
    expect(isWormholeEdgeRevealed(wormholeEdge, '0,0')).toBe(false)
  })

  it('filters wormhole edges in on-hover mode only when an endpoint is active', () => {
    const edges = [wormholeEdge, { source: 'p1', target: 'p2' }]
    expect(filterWormholeEdgesForDisplayMode(edges, 'always', null)).toHaveLength(2)
    expect(filterWormholeEdgesForDisplayMode(edges, 'on-hover', null)).toEqual([
      { source: 'p1', target: 'p2' },
    ])
    expect(filterWormholeEdgesForDisplayMode(edges, 'on-hover', '1,2')).toHaveLength(2)
  })
})
