import { describe, expect, it } from 'vitest'
import { headingTravelDeltaGameLy } from '../../lib/cartography/headingTravel'
import {
  clampFleetHeadingTrailExtendTurns,
  collectFleetHeadingTrails,
  fleetHeadingTrailEndpoint,
  fleetHeadingTrailFromRecord,
  fleetHeadingTrailOpacity,
  fleetHeadingTrailSegmentsFromRecord,
  FLEET_HEADING_TRAIL_CURRENT_OPACITY,
  FLEET_HEADING_TRAIL_MIN_OPACITY,
} from './fleetHeadingTrails'
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

describe('fleetHeadingTrailEndpoint', () => {
  it('places the endpoint one travelLy along heading (0 = north)', () => {
    const end = fleetHeadingTrailEndpoint(1000, 2000, {
      heading: 0,
      warp: 5,
      travelLyPerTurn: 25,
      trailStop: { x: 1000, y: 3000 },
    })
    expect(end).toEqual({ x: 1000, y: 2025 })
  })

  it('moves east at heading 90', () => {
    const end = fleetHeadingTrailEndpoint(1000, 2000, {
      heading: 90,
      warp: 3,
      travelLyPerTurn: 9,
      trailStop: { x: 2000, y: 2000 },
    })
    expect(end.x).toBeCloseTo(1009)
    expect(end.y).toBeCloseTo(2000)
  })

  it('clamps to trailStop when the stop is within one-turn range', () => {
    const end = fleetHeadingTrailEndpoint(1000, 2000, {
      heading: 90,
      warp: 9,
      travelLyPerTurn: 81,
      trailStop: { x: 1020, y: 2000 },
    })
    expect(end).toEqual({ x: 1020, y: 2000 })
  })

  it('does not clamp when trailStop is beyond one-turn range', () => {
    const end = fleetHeadingTrailEndpoint(1000, 2000, {
      heading: 90,
      warp: 5,
      travelLyPerTurn: 25,
      trailStop: { x: 1100, y: 2000 },
    })
    expect(end.x).toBeCloseTo(1025)
    expect(end.y).toBeCloseTo(2000)
  })
})

describe('fleetHeadingTrailOpacity', () => {
  it('keeps current-turn opacity when extend is 0 or offset is 0', () => {
    expect(fleetHeadingTrailOpacity(0, 0)).toBe(FLEET_HEADING_TRAIL_CURRENT_OPACITY)
    expect(fleetHeadingTrailOpacity(0, 5)).toBe(FLEET_HEADING_TRAIL_CURRENT_OPACITY)
    expect(fleetHeadingTrailOpacity(3, 0)).toBe(FLEET_HEADING_TRAIL_CURRENT_OPACITY)
  })

  it('ramps symmetrically to min opacity at max |offset|', () => {
    expect(fleetHeadingTrailOpacity(5, 5)).toBe(FLEET_HEADING_TRAIL_MIN_OPACITY)
    expect(fleetHeadingTrailOpacity(1, 5)).toBeCloseTo(
      FLEET_HEADING_TRAIL_CURRENT_OPACITY -
        (1 / 5) * (FLEET_HEADING_TRAIL_CURRENT_OPACITY - FLEET_HEADING_TRAIL_MIN_OPACITY)
    )
    expect(fleetHeadingTrailOpacity(3, 5)).toBeCloseTo(
      FLEET_HEADING_TRAIL_CURRENT_OPACITY -
        (3 / 5) * (FLEET_HEADING_TRAIL_CURRENT_OPACITY - FLEET_HEADING_TRAIL_MIN_OPACITY)
    )
  })
})

describe('clampFleetHeadingTrailExtendTurns', () => {
  it('clamps to 0..5', () => {
    expect(clampFleetHeadingTrailExtendTurns(-1)).toBe(0)
    expect(clampFleetHeadingTrailExtendTurns(2.9)).toBe(2)
    expect(clampFleetHeadingTrailExtendTurns(99)).toBe(5)
    expect(clampFleetHeadingTrailExtendTurns(Number.NaN)).toBe(0)
  })
})

describe('fleetHeadingTrailFromRecord', () => {
  it('returns null without lastSeen on the display turn or without motion', () => {
    expect(
      fleetHeadingTrailFromRecord(
        record({
          recordId: 'no-motion',
          lastSeen: { turn: 9, x: 1, y: 2 },
        }),
        1,
        9
      )
    ).toBeNull()

    expect(
      fleetHeadingTrailFromRecord(
        record({
          recordId: 'stale',
          lastSeen: { turn: 8, x: 1, y: 2 },
          motion: {
            heading: 0,
            warp: 9,
            travelLyPerTurn: 81,
            trailStop: { x: 1, y: 83 },
          },
        }),
        1,
        9
      )
    ).toBeNull()
  })

  it('builds a current-turn trail from lastSeen + motion', () => {
    const trail = fleetHeadingTrailFromRecord(
      record({
        recordId: 'r1',
        lastSeen: { turn: 9, x: 500, y: 600 },
        motion: {
          heading: 0,
          warp: 9,
          travelLyPerTurn: 81,
          trailStop: { x: 500, y: 800 },
        },
      }),
      3,
      9
    )
    expect(trail).toEqual({
      key: 'r1:t0:500,600',
      recordId: 'r1',
      playerId: 3,
      x: 500,
      y: 600,
      endX: 500,
      endY: 681,
      heading: 0,
      travelLyPerTurn: 81,
      turnOffset: 0,
      opacity: FLEET_HEADING_TRAIL_CURRENT_OPACITY,
    })
  })
})

describe('fleetHeadingTrailSegmentsFromRecord', () => {
  const underwayEast = record({
    recordId: 'east',
    lastSeen: { turn: 9, x: 1000, y: 2000 },
    motion: {
      heading: 90,
      warp: 5,
      travelLyPerTurn: 25,
      trailStop: { x: 2000, y: 2000 },
    },
  })

  it('emits only the current segment when extendTurns is 0', () => {
    const segments = fleetHeadingTrailSegmentsFromRecord(underwayEast, 1, 9, 0)
    expect(segments).toHaveLength(1)
    expect(segments[0]!.turnOffset).toBe(0)
    expect(segments[0]!.endX).toBeCloseTo(1025)
    expect(segments[0]!.endY).toBeCloseTo(2000)
  })

  it('adds matching forward and backward segments with shared opacity ladder', () => {
    const segments = fleetHeadingTrailSegmentsFromRecord(underwayEast, 1, 9, 2)
    const byOffset = new Map(segments.map((s) => [s.turnOffset, s]))
    expect([...byOffset.keys()].sort((a, b) => a - b)).toEqual([-2, -1, 0, 1, 2])

    expect(byOffset.get(0)!.x).toBe(1000)
    expect(byOffset.get(0)!.endX).toBeCloseTo(1025)
    expect(byOffset.get(1)!.x).toBeCloseTo(1025)
    expect(byOffset.get(1)!.endX).toBeCloseTo(1050)
    expect(byOffset.get(2)!.x).toBeCloseTo(1050)
    expect(byOffset.get(2)!.endX).toBeCloseTo(1075)

    expect(byOffset.get(-1)!.endX).toBeCloseTo(1000)
    expect(byOffset.get(-1)!.x).toBeCloseTo(975)
    expect(byOffset.get(-2)!.endX).toBeCloseTo(975)
    expect(byOffset.get(-2)!.x).toBeCloseTo(950)

    expect(byOffset.get(1)!.opacity).toBe(byOffset.get(-1)!.opacity)
    expect(byOffset.get(2)!.opacity).toBe(byOffset.get(-2)!.opacity)
    expect(byOffset.get(0)!.opacity).toBeGreaterThan(byOffset.get(1)!.opacity)
    expect(byOffset.get(1)!.opacity).toBeGreaterThan(byOffset.get(2)!.opacity)
  })

  it('stops further forward segments after clamping at trailStop', () => {
    const nearStop = record({
      recordId: 'near',
      lastSeen: { turn: 9, x: 1000, y: 2000 },
      motion: {
        heading: 90,
        warp: 9,
        travelLyPerTurn: 81,
        trailStop: { x: 1040, y: 2000 },
      },
    })
    const segments = fleetHeadingTrailSegmentsFromRecord(nearStop, 2, 9, 3)
    const forward = segments.filter((s) => s.turnOffset >= 0)
    expect(forward).toHaveLength(1)
    expect(forward[0]!.endX).toBe(1040)
    expect(forward[0]!.endY).toBe(2000)
    expect(segments.filter((s) => s.turnOffset < 0)).toHaveLength(3)
  })

  it('clamps a later forward segment when trailStop falls mid-path', () => {
    const midPathStop = record({
      recordId: 'mid',
      lastSeen: { turn: 9, x: 1000, y: 2000 },
      motion: {
        heading: 90,
        warp: 5,
        travelLyPerTurn: 25,
        trailStop: { x: 1060, y: 2000 },
      },
    })
    const segments = fleetHeadingTrailSegmentsFromRecord(midPathStop, 1, 9, 5)
    const forward = segments
      .filter((s) => s.turnOffset >= 0)
      .sort((a, b) => a.turnOffset - b.turnOffset)
    expect(forward.map((s) => s.turnOffset)).toEqual([0, 1, 2])
    expect(forward[2]!.endX).toBe(1060)
    expect(forward[2]!.endY).toBe(2000)
  })
})

describe('collectFleetHeadingTrails', () => {
  it('includes only visible active ships with motion on the shell turn', () => {
    const byId = new Map<number, FleetPlayerStreamSlice>([
      [
        1,
        {
          playerName: 'Alice',
          records: [
            record({
              recordId: 'a-ok',
              lastSeen: { turn: 9, x: 10, y: 20 },
              motion: {
                heading: 90,
                warp: 4,
                travelLyPerTurn: 16,
                trailStop: { x: 100, y: 20 },
              },
            }),
            record({
              recordId: 'a-lost',
              disposition: 'lost',
              lastSeen: { turn: 9, x: 10, y: 20 },
              motion: {
                heading: 90,
                warp: 4,
                travelLyPerTurn: 16,
                trailStop: { x: 100, y: 20 },
              },
            }),
            record({
              recordId: 'a-no-motion',
              lastSeen: { turn: 9, x: 11, y: 21 },
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
      [
        2,
        {
          playerName: 'Bob',
          records: [
            record({
              recordId: 'b-hidden',
              lastSeen: { turn: 9, x: 30, y: 40 },
              motion: {
                heading: 0,
                warp: 9,
                travelLyPerTurn: 81,
                trailStop: { x: 30, y: 200 },
              },
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

    const trails = collectFleetHeadingTrails(byId, [{ playerId: 1, name: 'Alice' }], 9, 0)
    expect(trails).toHaveLength(1)
    expect(trails[0]!.recordId).toBe('a-ok')
    expect(trails[0]!.playerId).toBe(1)
    const { dx, dy } = headingTravelDeltaGameLy(90, 16)
    expect(trails[0]!.endX).toBeCloseTo(10 + dx)
    expect(trails[0]!.endY).toBeCloseTo(20 + dy)
  })
})
