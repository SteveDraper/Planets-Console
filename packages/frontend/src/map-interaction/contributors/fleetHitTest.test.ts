import { describe, it, expect } from 'vitest'
import { hitTestFleetAtPointer } from './fleetHitTest'
import type { FleetLocationRingStack } from '../../analytics/fleet/fleetLocationRings'
import type { MapHitContext } from '../mapInteractionContributorTypes'

function sampleStack(): FleetLocationRingStack {
  return {
    key: '1000,2000',
    x: 1000,
    y: 2000,
    shipCount: 1,
    hostMilitaryPointsSum: 20,
    strengthFraction: 0.003,
    diameterPx: 10,
    opacity: 0.4,
    strokeWidthPx: 2.5,
    arcs: [
      {
        playerId: 8,
        playerName: 'Alice',
        shipCount: 1,
        share: 1,
        ships: [
          {
            recordId: 'a1',
            playerId: 8,
            playerName: 'Alice',
            shipIdLabel: '101',
            hullId: 13,
            hullLabel: 'Cruiser A',
            hostMilitaryPoints: 20,
            x: 1000,
            y: 2000,
          },
        ],
      },
    ],
    ships: [],
  }
}

describe('hitTestFleetAtPointer', () => {
  it('returns stack and flow anchor under the ring', () => {
    const domNode = document.createElement('div')
    domNode.getBoundingClientRect = () =>
      ({
        left: 0,
        top: 0,
        right: 800,
        bottom: 600,
        width: 800,
        height: 600,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect

    const hit: MapHitContext = {
      clientPos: { x: 1000.5, y: -2000.5 },
      hitEpoch: 1,
      domNode,
      transform: [0, 0, 1],
    }

    const result = hitTestFleetAtPointer(hit, [sampleStack()])
    expect(result?.stack.key).toBe('1000,2000')
    expect(result?.flowX).toBeCloseTo(1000.5)
    expect(result?.flowY).toBeCloseTo(-2000.5)
  })
})
