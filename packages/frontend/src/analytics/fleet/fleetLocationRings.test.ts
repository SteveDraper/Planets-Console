import { describe, expect, it } from 'vitest'
import { defaultColorForPlayerId } from '../../lib/playerColor'
import { EMPTY_FLEET_COMPONENT_CATALOG } from './fleetComponentCatalog'
import {
  buildFleetLocationRingStacks,
  collectFleetLocationRingShips,
  fleetLocationRingDiameterPx,
  fleetLocationRingOpacity,
  fleetLocationRingShipFromRecord,
  hostMilitaryPointsFromEstimate2x,
} from './fleetLocationRings'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import type { FleetTableRecord } from './fleetTableWireSchema'

function record(partial: Partial<FleetTableRecord> & Pick<FleetTableRecord, 'recordId'>): FleetTableRecord {
  return {
    disposition: 'active',
    qualifiers: {},
    fields: {
      shipId: { kind: 'known', value: 1 },
      hull: { kind: 'known', value: 13 },
      engine: { kind: 'unknown' },
      beams: { kind: 'unknown' },
      launchers: { kind: 'unknown' },
      builtTurn: { kind: 'unknown' },
      location: { kind: 'unknown' },
    },
    buildOptionSets: [],
    ...partial,
  }
}

describe('fleetLocationRingDiameterPx', () => {
  it('is 12px for a single ship', () => {
    expect(fleetLocationRingDiameterPx(1)).toBe(12)
  })

  it('grows with floor(log2(shipCount)) and caps at 20', () => {
    expect(fleetLocationRingDiameterPx(2)).toBe(14)
    expect(fleetLocationRingDiameterPx(3)).toBe(14)
    expect(fleetLocationRingDiameterPx(4)).toBe(16)
    expect(fleetLocationRingDiameterPx(8)).toBe(18)
    expect(fleetLocationRingDiameterPx(16)).toBe(20)
    expect(fleetLocationRingDiameterPx(1024)).toBe(20)
  })

  it('treats non-positive counts as 1 ship', () => {
    expect(fleetLocationRingDiameterPx(0)).toBe(12)
    expect(fleetLocationRingDiameterPx(-3)).toBe(12)
  })
})

describe('fleetLocationRingOpacity', () => {
  it('clamps to [0.40, 0.95] and uses Emax of at least 1', () => {
    expect(fleetLocationRingOpacity(0, 0)).toBe(0.4)
    expect(fleetLocationRingOpacity(0, 100)).toBe(0.4)
    expect(fleetLocationRingOpacity(100, 100)).toBe(0.95)
    expect(fleetLocationRingOpacity(50, 100)).toBeCloseTo(0.675)
  })
})

describe('hostMilitaryPointsFromEstimate2x', () => {
  it('halves the scaled estimate and omits when missing', () => {
    expect(hostMilitaryPointsFromEstimate2x(42)).toBe(21)
    expect(hostMilitaryPointsFromEstimate2x(undefined)).toBeNull()
  })
})

describe('buildFleetLocationRingStacks', () => {
  it('stacks exact coordinates and splits arcs by player share', () => {
    const ships = [
      {
        recordId: 'a',
        playerId: 8,
        playerName: 'Alice',
        shipIdLabel: '1',
        hullId: 13,
        hullLabel: 'Cruiser',
        hostMilitaryPoints: 10,
        x: 100,
        y: 200,
      },
      {
        recordId: 'b',
        playerId: 9,
        playerName: 'Bob',
        shipIdLabel: '2',
        hullId: 24,
        hullLabel: 'Serpent',
        hostMilitaryPoints: 30,
        x: 100,
        y: 200,
      },
      {
        recordId: 'c',
        playerId: 8,
        playerName: 'Alice',
        shipIdLabel: '3',
        hullId: 13,
        hullLabel: 'Cruiser',
        hostMilitaryPoints: 10,
        x: 100,
        y: 200,
      },
      {
        recordId: 'd',
        playerId: 8,
        playerName: 'Alice',
        shipIdLabel: '4',
        hullId: 13,
        hullLabel: 'Cruiser',
        hostMilitaryPoints: 5,
        x: 50,
        y: 50,
      },
    ]

    const stacks = buildFleetLocationRingStacks(ships)
    expect(stacks).toHaveLength(2)

    const stacked = stacks.find((s) => s.key === '100,200')!
    expect(stacked.shipCount).toBe(3)
    expect(stacked.hostMilitaryPointsSum).toBe(50)
    expect(stacked.diameterPx).toBe(14)
    expect(stacked.opacity).toBe(0.95)
    expect(stacked.arcs).toHaveLength(2)
    expect(stacked.arcs[0]).toMatchObject({
      playerId: 8,
      shipCount: 2,
      share: 2 / 3,
      color: defaultColorForPlayerId(8),
    })
    expect(stacked.arcs[1]).toMatchObject({
      playerId: 9,
      shipCount: 1,
      share: 1 / 3,
      color: defaultColorForPlayerId(9),
    })

    const alone = stacks.find((s) => s.key === '50,50')!
    expect(alone.shipCount).toBe(1)
    expect(alone.hostMilitaryPointsSum).toBe(5)
    expect(alone.opacity).toBeCloseTo(0.4 + 0.55 * (5 / 50))
  })

  it('excludes records without lastSeen via collect path', () => {
    const streamPlayersById = new Map<number, FleetPlayerStreamSlice>([
      [
        8,
        {
          playerName: 'Alice',
          records: [
            record({
              recordId: 'with-pos',
              lastSeen: { turn: 9, x: 1, y: 2 },
              militaryEstimate2x: 20,
            }),
            record({ recordId: 'no-pos' }),
            record({
              recordId: 'lost',
              disposition: 'lost',
              lastSeen: { turn: 9, x: 1, y: 2 },
            }),
          ],
          discrepancyOverlay: 'inherit',
          isComplete: true,
          isFinal: true,
          isPending: false,
          summary: 'ok',
          error: null,
        },
      ],
    ])

    const ships = collectFleetLocationRingShips(
      streamPlayersById,
      [{ playerId: 8, name: 'Alice' }],
      EMPTY_FLEET_COMPONENT_CATALOG
    )
    expect(ships).toHaveLength(1)
    expect(ships[0]!.recordId).toBe('with-pos')
    expect(ships[0]!.hostMilitaryPoints).toBe(10)
  })
})

describe('fleetLocationRingShipFromRecord', () => {
  it('returns null without lastSeen', () => {
    expect(
      fleetLocationRingShipFromRecord(
        record({ recordId: 'x' }),
        1,
        'P',
        EMPTY_FLEET_COMPONENT_CATALOG
      )
    ).toBeNull()
  })
})
