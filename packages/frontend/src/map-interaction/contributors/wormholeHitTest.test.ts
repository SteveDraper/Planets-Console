import { describe, it, expect } from 'vitest'
import type { MapEdge } from '../../api/bff'
import { buildWormholeEndpointHoverIndex } from '../../lib/wormholeEndpointHover'
import type { MapHitContext } from '../mapInteractionContributorTypes'
import {
  hitTestWormholeAtPointer,
  wormholeHoverLabel,
} from './wormholeHitTest'

function hitAtFlow(
  flowX: number,
  flowY: number,
  scale = 1
): MapHitContext {
  const left = 0
  const top = 0
  const tx = 0
  const ty = 0
  // flow = (pane - translation) / scale → pane = flow * scale + translation
  const clientX = left + flowX * scale + tx
  const clientY = top + flowY * scale + ty
  return {
    clientPos: { x: clientX, y: clientY },
    hitEpoch: 1,
    domNode: {
      getBoundingClientRect: () =>
        ({
          left,
          top,
          width: 1000,
          height: 1000,
          right: 1000,
          bottom: 1000,
          x: left,
          y: top,
          toJSON: () => ({}),
        }) as DOMRect,
    } as HTMLElement,
    transform: [tx, ty, scale],
  }
}

const bidirectionalEdge: MapEdge = {
  source: 'a',
  target: 'b',
  layer: 'wormholes',
  isBidirectional: true,
  sourceGameX: 10,
  sourceGameY: 20,
  targetGameX: 30,
  targetGameY: 40,
}

describe('wormholeHoverLabel', () => {
  it('labels bidirectional ends', () => {
    expect(wormholeHoverLabel(bidirectionalEdge, true)).toBe('goes to (30, 40)')
    expect(wormholeHoverLabel(bidirectionalEdge, false)).toBe('goes to (10, 20)')
  })

  it('labels one-way entrance and exit', () => {
    const oneWay = { ...bidirectionalEdge, isBidirectional: false }
    expect(wormholeHoverLabel(oneWay, true)).toBe('goes to (30, 40)')
    expect(wormholeHoverLabel(oneWay, false)).toBe('exit - entrance at (10, 20)')
  })
})

describe('hitTestWormholeAtPointer', () => {
  const hoverByCell = buildWormholeEndpointHoverIndex([bidirectionalEdge])

  it('hits an endpoint cell and returns map-element lines', () => {
    // Cell (10, 20) center is flow (10.5, -20.5)
    const result = hitTestWormholeAtPointer(
      hitAtFlow(10.5, -20.5),
      hoverByCell,
      [bidirectionalEdge]
    )
    expect(result).not.toBeNull()
    expect(result!.id).toBe('wormhole:endpoint:10,20')
    expect(result!.lines[0]).toMatch(/wormhole to \(30, 40\)/)
    expect(result!.revealMapX).toBe(10)
    expect(result!.revealMapY).toBe(20)
  })

  it('prefers endpoint over edge when both are under the pointer', () => {
    const result = hitTestWormholeAtPointer(
      hitAtFlow(10.5, -20.5),
      hoverByCell,
      [bidirectionalEdge]
    )
    expect(result!.id.startsWith('wormhole:endpoint:')).toBe(true)
  })

  it('hits edge mid-line when away from endpoints', () => {
    // Midpoint between (10.5,-20.5) and (30.5,-40.5)
    const midX = (10.5 + 30.5) / 2
    const midY = (-20.5 + -40.5) / 2
    const result = hitTestWormholeAtPointer(
      hitAtFlow(midX, midY),
      hoverByCell,
      [bidirectionalEdge]
    )
    expect(result).not.toBeNull()
    expect(result!.id.startsWith('wormhole:edge:')).toBe(true)
    expect(result!.lines).toHaveLength(1)
  })

  it('returns null when pointer is far from wormholes', () => {
    expect(
      hitTestWormholeAtPointer(hitAtFlow(500, -500), hoverByCell, [
        bidirectionalEdge,
      ])
    ).toBeNull()
  })
})
