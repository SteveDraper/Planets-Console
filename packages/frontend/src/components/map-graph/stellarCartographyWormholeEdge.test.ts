import { describe, expect, it } from 'vitest'
import { wormholeHoverLabel, type WormholeEdgeData } from './stellarCartographyWormholeEdge'

const edgeData: WormholeEdgeData = {
  sourceGameX: 10,
  sourceGameY: 20,
  targetGameX: 30,
  targetGameY: 40,
}

describe('wormholeHoverLabel', () => {
  it('labels both ends of bidirectional wormholes as destinations', () => {
    const bidirectional = { ...edgeData, isBidirectional: true }
    expect(wormholeHoverLabel(bidirectional, true)).toBe('goes to (30, 40)')
    expect(wormholeHoverLabel(bidirectional, false)).toBe('goes to (10, 20)')
  })

  it('labels the exit end of one-way wormholes with its entrance', () => {
    const oneWay = { ...edgeData, isBidirectional: false }
    expect(wormholeHoverLabel(oneWay, true)).toBe('goes to (30, 40)')
    expect(wormholeHoverLabel(oneWay, false)).toBe('exit - entrance at (10, 20)')
  })
})
