import { describe, expect, it } from 'vitest'
import type { MapEdge } from '../api/bff'
import {
  buildWormholeEndpointHoverIndex,
  formatWormholeEndpointHoverLines,
  wormholeEndpointRecenterGameCoords,
} from './wormholeEndpointHover'

describe('wormholeEndpointHover', () => {
  it('indexes bidirectional endpoints with shared stability and reciprocal other ends', () => {
    const index = buildWormholeEndpointHoverIndex([
      {
        source: 'a',
        target: 'b',
        layer: 'wormholes',
        isBidirectional: true,
        stability: 80,
        sourceGameX: 10,
        sourceGameY: 20,
        targetGameX: 30,
        targetGameY: 40,
      },
    ])
    expect(formatWormholeEndpointHoverLines(index.get('10,20')!)).toEqual([
      'stability: 80',
      'wormhole to (30, 40)',
    ])
    expect(formatWormholeEndpointHoverLines(index.get('30,40')!)).toEqual([
      'stability: 80',
      'wormhole to (10, 20)',
    ])
  })

  it('indexes mono-directional endpoints as entry and exit only', () => {
    const index = buildWormholeEndpointHoverIndex([
      {
        source: 'a',
        target: 'b',
        layer: 'wormholes',
        isBidirectional: false,
        stability: 50,
        sourceGameX: 1,
        sourceGameY: 2,
        targetGameX: 9,
        targetGameY: 8,
      } satisfies MapEdge,
    ])
    expect(formatWormholeEndpointHoverLines(index.get('1,2')!)).toEqual([
      'stability: 50',
      'wormhole to (9, 8)',
      'entry only',
    ])
    expect(formatWormholeEndpointHoverLines(index.get('9,8')!)).toEqual([
      'stability: 50',
      'wormhole from (1, 2)',
      'exit only',
    ])
  })

  it('ignores non-wormhole edges', () => {
    const index = buildWormholeEndpointHoverIndex([
      { source: 'p1', target: 'p2', sourceGameX: 0, sourceGameY: 0, targetGameX: 1, targetGameY: 1 },
    ])
    expect(index.size).toBe(0)
  })

  it('indexes unknown-target entrances as unexplored', () => {
    const index = buildWormholeEndpointHoverIndex([], [{ x: 99, y: 88 }])
    expect(formatWormholeEndpointHoverLines(index.get('99,88')!)).toEqual(['unexplored'])
    expect(wormholeEndpointRecenterGameCoords(index.get('99,88')!)).toBeNull()
  })

  it('returns other-end map coords for known endpoint click recenter', () => {
    const index = buildWormholeEndpointHoverIndex([
      {
        source: 'a',
        target: 'b',
        layer: 'wormholes',
        isBidirectional: true,
        sourceGameX: 10,
        sourceGameY: 20,
        targetGameX: 30,
        targetGameY: 40,
      },
    ])
    expect(wormholeEndpointRecenterGameCoords(index.get('10,20')!)).toEqual({ x: 30, y: 40 })
  })
})
