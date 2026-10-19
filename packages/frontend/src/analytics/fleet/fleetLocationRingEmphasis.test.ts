import { describe, expect, it } from 'vitest'
import {
  emphasisedPlayerIdsForRingHover,
  fleetLocationRingArcEmphasis,
  fleetLocationRingEmphasisOutlineColor,
  fleetLocationRingPaintLayers,
} from './fleetLocationRingEmphasis'
import {
  buildFleetLocationRingStacks,
  type FleetLocationRingShip,
} from './fleetLocationRings'

function ship(
  partial: Partial<FleetLocationRingShip> &
    Pick<FleetLocationRingShip, 'recordId' | 'playerId' | 'x' | 'y'>
): FleetLocationRingShip {
  return {
    playerName: `Player ${partial.playerId}`,
    shipIdLabel: partial.recordId,
    hullId: 1,
    hullLabel: 'Hull',
    warp: null,
    hostMilitaryPoints: 0,
    ...partial,
  }
}

describe('fleet location ring emphasis membership', () => {
  const ringA = buildFleetLocationRingStacks([
    ship({ recordId: 'a1', playerId: 1, x: 0, y: 0 }),
    ship({ recordId: 'a2', playerId: 2, x: 0, y: 0 }),
  ])[0]!
  const ringB = buildFleetLocationRingStacks([
    ship({ recordId: 'b2', playerId: 2, x: 10, y: 0 }),
    ship({ recordId: 'b3', playerId: 3, x: 10, y: 0 }),
  ])[0]!

  it('hovering a ring emphasises every arc player, including on other rings', () => {
    const emphasised = new Set(emphasisedPlayerIdsForRingHover(ringA))
    expect([...emphasised]).toEqual([1, 2])
    expect(fleetLocationRingArcEmphasis(1, emphasised)).toBe('emphasis')
    expect(fleetLocationRingArcEmphasis(2, emphasised)).toBe('emphasis')
    expect(fleetLocationRingArcEmphasis(ringB.arcs[0]!.playerId, emphasised)).toBe('emphasis')
    expect(fleetLocationRingArcEmphasis(ringB.arcs[1]!.playerId, emphasised)).toBe('rest')
  })

  it('emphasises by player id so a co-located other player stays at rest', () => {
    const emphasised = new Set([2])
    expect(fleetLocationRingArcEmphasis(2, emphasised)).toBe('emphasis')
    expect(fleetLocationRingArcEmphasis(1, emphasised)).toBe('rest')
    expect(fleetLocationRingArcEmphasis(3, emphasised)).toBe('rest')
  })
})

describe('temporary fleet location rings', () => {
  it('does not resize a co-located rest ring', () => {
    const restShips = [
      ship({
        recordId: 'visible',
        playerId: 1,
        x: 5,
        y: 5,
        hostMilitaryPoints: 0,
      }),
    ]
    const temporaryShips = Array.from({ length: 7 }, (_, index) =>
      ship({
        recordId: `hidden-${index}`,
        playerId: 2,
        x: 5,
        y: 5,
        hostMilitaryPoints: 10_000,
      })
    )

    const restAlone = buildFleetLocationRingStacks(restShips)
    const layers = fleetLocationRingPaintLayers(restShips, temporaryShips)

    expect(layers.restStacks).toEqual(restAlone)
    expect(layers.restStacks[0]).toMatchObject({
      shipCount: 1,
      diameterPx: 14,
      opacity: 0.5,
      strokeWidthPx: 2.5,
      arcs: [expect.objectContaining({ playerId: 1, share: 1 })],
    })
    expect(layers.temporaryStacks).toHaveLength(1)
    expect(layers.temporaryStacks[0]).toMatchObject({
      shipCount: 7,
      diameterPx: 18,
      strengthFraction: 1,
      opacity: 0.95,
      arcs: [expect.objectContaining({ playerId: 2, share: 1 })],
    })
    expect(layers.temporaryStacks[0]!.key).toBe(layers.restStacks[0]!.key)
  })
})

describe('fleetLocationRingEmphasisOutlineColor', () => {
  it('picks a light outline on a dark stroke and a dark outline on a light stroke', () => {
    expect(fleetLocationRingEmphasisOutlineColor('#000000')).toBe('#f8fafc')
    expect(fleetLocationRingEmphasisOutlineColor('#ffffff')).toBe('#0b1220')
    expect(fleetLocationRingEmphasisOutlineColor('not-a-color')).toBe('#f8fafc')
  })
})
