import { describe, expect, it } from 'vitest'
import { findFleetLocationRingStackAtPanePoint } from './fleetLocationRingHitTest'
import type { FleetLocationRingStack } from './fleetLocationRings'

function stackAt(
  x: number,
  y: number,
  diameterPx: number
): FleetLocationRingStack {
  return {
    key: `${x},${y}`,
    x,
    y,
    shipCount: 1,
    hostMilitaryPointsSum: 0,
    strengthFraction: 0,
    diameterPx,
    opacity: 0.4,
    strokeWidthPx: 2.5,
    arcs: [],
    ships: [],
  }
}

describe('findFleetLocationRingStackAtPanePoint', () => {
  it('hits the stack whose pane disk covers the point', () => {
    // flow center for (100,200) at identity transform: (100.5, -200.5)
    const stacks = [stackAt(100, 200, 12)]
    const transform: [number, number, number] = [0, 0, 1]
    const hit = findFleetLocationRingStackAtPanePoint(stacks, 100.5, -200.5, transform)
    expect(hit?.key).toBe('100,200')
  })

  it('returns null when outside the hit radius', () => {
    const stacks = [stackAt(100, 200, 8)]
    const transform: [number, number, number] = [0, 0, 1]
    // diameter 8 → outer R=4 + pad 4 = 8px hit radius
    expect(
      findFleetLocationRingStackAtPanePoint(stacks, 100.5 + 20, -200.5, transform)
    ).toBeNull()
  })

  it('picks the closer stack when disks overlap', () => {
    const stacks = [stackAt(100, 200, 20), stackAt(102, 200, 20)]
    const transform: [number, number, number] = [0, 0, 1]
    const hit = findFleetLocationRingStackAtPanePoint(stacks, 100.5, -200.5, transform)
    expect(hit?.key).toBe('100,200')
  })
})
