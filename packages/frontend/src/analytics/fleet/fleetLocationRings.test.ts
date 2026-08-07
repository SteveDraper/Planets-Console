import { describe, expect, it } from 'vitest'
import { defaultColorForPlayerId } from '../../lib/playerColor'
import { EMPTY_FLEET_COMPONENT_CATALOG } from './fleetComponentCatalog'
import {
  buildFleetLocationRingStacks,
  collectFleetLocationRingShips,
  fleetLocationRingDiameterPx,
  fleetLocationRingOpacity,
  fleetLocationRingPaintRadiusPx,
  fleetLocationRingShipFromRecord,
  fleetLocationRingStrengthFraction,
  fleetLocationRingStrokeWidthPx,
  FLEET_LOCATION_RING_DEFAULT_STRENGTH_SCALE,
  FLEET_LOCATION_RING_MIN_STROKE_WIDTH_PX,
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
  it('is 8px for a single ship', () => {
    expect(fleetLocationRingDiameterPx(1)).toBe(8)
  })

  it('grows with floor(log2(shipCount)) and caps at 20', () => {
    expect(fleetLocationRingDiameterPx(2)).toBe(10)
    expect(fleetLocationRingDiameterPx(3)).toBe(10)
    expect(fleetLocationRingDiameterPx(4)).toBe(12)
    expect(fleetLocationRingDiameterPx(8)).toBe(14)
    expect(fleetLocationRingDiameterPx(16)).toBe(16)
    expect(fleetLocationRingDiameterPx(32)).toBe(18)
    expect(fleetLocationRingDiameterPx(64)).toBe(20)
    expect(fleetLocationRingDiameterPx(1024)).toBe(20)
  })

  it('treats non-positive counts as 1 ship', () => {
    expect(fleetLocationRingDiameterPx(0)).toBe(8)
    expect(fleetLocationRingDiameterPx(-3)).toBe(8)
  })
})

describe('fleetLocationRingStrengthFraction', () => {
  it('normalizes against an absolute scale and clamps to [0, 1]', () => {
    expect(fleetLocationRingStrengthFraction(0, 10_000)).toBe(0)
    expect(fleetLocationRingStrengthFraction(5_000, 10_000)).toBe(0.5)
    expect(fleetLocationRingStrengthFraction(10_000, 10_000)).toBe(1)
    expect(fleetLocationRingStrengthFraction(20_000, 10_000)).toBe(1)
    expect(fleetLocationRingStrengthFraction(50, 0)).toBe(1)
  })
})

describe('fleetLocationRingOpacity', () => {
  it('clamps to [0.40, 0.95] from strength fraction', () => {
    expect(fleetLocationRingOpacity(0)).toBe(0.4)
    expect(fleetLocationRingOpacity(1)).toBe(0.95)
    expect(fleetLocationRingOpacity(0.5)).toBeCloseTo(0.675)
  })
})

describe('fleetLocationRingStrokeWidthPx', () => {
  it('keeps a minimum stroke for weak stacks and fills to center at full strength', () => {
    expect(fleetLocationRingStrokeWidthPx(8, 0)).toBe(FLEET_LOCATION_RING_MIN_STROKE_WIDTH_PX)
    expect(fleetLocationRingStrokeWidthPx(8, 1)).toBe(4)
    expect(fleetLocationRingStrokeWidthPx(20, 0.5)).toBe(5)
  })
})

describe('fleetLocationRingPaintRadiusPx', () => {
  it('keeps the outer edge at diameter/2', () => {
    expect(fleetLocationRingPaintRadiusPx(8, 2.5)).toBeCloseTo(2.75)
    expect(fleetLocationRingPaintRadiusPx(8, 4)).toBe(2)
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

    const stacks = buildFleetLocationRingStacks(ships, 100)
    expect(stacks).toHaveLength(2)

    const stacked = stacks.find((s) => s.key === '100,200')!
    expect(stacked.shipCount).toBe(3)
    expect(stacked.hostMilitaryPointsSum).toBe(50)
    expect(stacked.diameterPx).toBe(10)
    expect(stacked.strengthFraction).toBe(0.5)
    expect(stacked.opacity).toBeCloseTo(0.675)
    expect(stacked.strokeWidthPx).toBe(FLEET_LOCATION_RING_MIN_STROKE_WIDTH_PX)
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
    expect(alone.strengthFraction).toBe(0.05)
    expect(alone.opacity).toBeCloseTo(0.4 + 0.55 * 0.05)
    expect(alone.diameterPx).toBe(8)
  })

  it('defaults strength scale to 10000', () => {
    const ships = [
      {
        recordId: 'a',
        playerId: 1,
        playerName: 'P',
        shipIdLabel: '1',
        hullId: 13,
        hullLabel: 'Cruiser',
        hostMilitaryPoints: FLEET_LOCATION_RING_DEFAULT_STRENGTH_SCALE,
        x: 0,
        y: 0,
      },
    ]
    const [stack] = buildFleetLocationRingStacks(ships)
    expect(stack!.strengthFraction).toBe(1)
    expect(stack!.opacity).toBe(0.95)
    expect(stack!.strokeWidthPx).toBe(4)
  })

  it('excludes records without lastSeen or lastSeen on another turn', () => {
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
            record({
              recordId: 'stale-pos',
              lastSeen: { turn: 8, x: 3, y: 4 },
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
      EMPTY_FLEET_COMPONENT_CATALOG,
      9
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
        EMPTY_FLEET_COMPONENT_CATALOG,
        9
      )
    ).toBeNull()
  })

  it('returns null when lastSeen turn differs from the displayed shell turn', () => {
    expect(
      fleetLocationRingShipFromRecord(
        record({
          recordId: 'stale',
          lastSeen: { turn: 8, x: 1, y: 2 },
        }),
        1,
        'P',
        EMPTY_FLEET_COMPONENT_CATALOG,
        9
      )
    ).toBeNull()
  })
})
