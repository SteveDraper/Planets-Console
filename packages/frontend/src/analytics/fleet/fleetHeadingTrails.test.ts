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
import type { WarpWellMapCell } from '../../lib/warpWell'
import type { FleetTrailPlanetStop } from './fleetHeadingTrailPlanetStops'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import type { FleetTableRecord } from './fleetTableWireSchema'

/** Test fixture mirroring Core NORMAL well cell enumeration. */
function normalWellCellsAround(px: number, py: number): WarpWellMapCell[] {
  const out: WarpWellMapCell[] = []
  for (let dgx = -3; dgx <= 3; dgx += 1) {
    for (let dgy = -3; dgy <= 3; dgy += 1) {
      const gx = px + dgx
      const gy = py + dgy
      if (Math.hypot(gx - px, gy - py) <= 3) {
        out.push({ x: gx, y: gy })
      }
    }
  }
  return out
}

function planetStop(x: number, y: number): FleetTrailPlanetStop {
  return { x, y, wellCells: normalWellCellsAround(x, y) }
}

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

  it('skips planet/well clamps at warp 1 while still honoring trailStop', () => {
    // End-of-turn (1001) is in the well of planet 1004; W2+ would snap to 1004.
    const planets = [planetStop(1004, 2000)]
    const withoutStop = fleetHeadingTrailEndpoint(
      1000,
      2000,
      {
        heading: 90,
        warp: 1,
        travelLyPerTurn: 1,
        trailStop: { x: 1100, y: 2000 },
      },
      planets
    )
    expect(withoutStop.x).toBeCloseTo(1001)
    expect(withoutStop.y).toBeCloseTo(2000)

    const withStop = fleetHeadingTrailEndpoint(
      1000,
      2000,
      {
        heading: 90,
        warp: 1,
        travelLyPerTurn: 1,
        trailStop: { x: 1000.5, y: 2000 },
      },
      planets
    )
    expect(withStop.x).toBeCloseTo(1000.5)
    expect(withStop.y).toBeCloseTo(2000)
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
      isHyperjump: false,
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

  it('forces current-turn only for hyperjump even when extendTurns is set', () => {
    const origin = { x: 2458, y: 2128 }
    const landing = { x: 2311, y: 2441 }
    const travelLyPerTurn = Math.hypot(landing.x - origin.x, landing.y - origin.y)
    const hyp = record({
      recordId: 'hyp',
      lastSeen: { turn: 9, x: origin.x, y: origin.y },
      motion: {
        heading: 335,
        warp: 7,
        travelLyPerTurn,
        trailStop: landing,
        hyperjump: true,
      },
    })
    const intervening = [planetStop(2400, 2200)]
    const segments = fleetHeadingTrailSegmentsFromRecord(hyp, 2, 9, 5, intervening)
    expect(segments).toHaveLength(1)
    expect(segments[0]!.turnOffset).toBe(0)
    expect(segments[0]!.isHyperjump).toBe(true)
    expect(segments[0]!.endX).toBe(landing.x)
    expect(segments[0]!.endY).toBe(landing.y)
  })

  it('clamps forward legs at an intervening planet well', () => {
    const ship = record({
      recordId: 'well',
      lastSeen: { turn: 9, x: 1000, y: 2000 },
      motion: {
        heading: 90,
        warp: 9,
        travelLyPerTurn: 81,
        trailStop: { x: 2000, y: 2000 },
      },
    })
    // Exact planet lies on the eastbound one-turn segment (1000 → 1081).
    const planets = [planetStop(1040, 2000)]
    const segments = fleetHeadingTrailSegmentsFromRecord(ship, 1, 9, 2, planets)
    const forward = segments.filter((s) => s.turnOffset >= 0)
    expect(forward).toHaveLength(1)
    expect(forward[0]!.endX).toBe(1040)
    expect(forward[0]!.endY).toBe(2000)
  })

  it('does not apply planet/well path clamps at warp 1 (W1 well-pull exemption)', () => {
    const ship = record({
      recordId: 'w1',
      lastSeen: { turn: 9, x: 1000, y: 2000 },
      motion: {
        heading: 90,
        warp: 1,
        travelLyPerTurn: 1,
        // Core keeps trailStop at the raw waypoint for W1 (no well snap).
        trailStop: { x: 1100, y: 2000 },
      },
    })
    // Planet at 1004: one-turn end (1001) sits in its well (≤3 ly). W2+ would
    // snap the endpoint to the planet center; W1 must keep travelLy motion.
    const planets = [planetStop(1004, 2000)]
    const segments = fleetHeadingTrailSegmentsFromRecord(ship, 1, 9, 3, planets)
    const byOffset = new Map(segments.map((s) => [s.turnOffset, s]))
    expect(byOffset.get(0)!.endX).toBeCloseTo(1001)
    expect(byOffset.get(0)!.endY).toBeCloseTo(2000)
    expect(byOffset.get(1)!.endX).toBeCloseTo(1002)
    expect(byOffset.get(-1)!.x).toBeCloseTo(999)
    expect(byOffset.get(-1)!.endX).toBeCloseTo(1000)
  })

  it('still clamps W1 forward legs to Core trailStop', () => {
    const ship = record({
      recordId: 'w1-stop',
      lastSeen: { turn: 9, x: 1000, y: 2000 },
      motion: {
        heading: 90,
        warp: 1,
        travelLyPerTurn: 1,
        trailStop: { x: 1002, y: 2000 },
      },
    })
    // Would snap to planet center under W2+ path clamps; W1 ignores it.
    const planets = [planetStop(1004, 2000)]
    const segments = fleetHeadingTrailSegmentsFromRecord(ship, 1, 9, 5, planets)
    const forward = segments
      .filter((s) => s.turnOffset >= 0)
      .sort((a, b) => a.turnOffset - b.turnOffset)
    expect(forward.map((s) => s.turnOffset)).toEqual([0, 1])
    expect(forward[0]!.endX).toBeCloseTo(1001)
    expect(forward[1]!.endX).toBe(1002)
    expect(forward[1]!.endY).toBe(2000)
  })

  it('emits W1 back-trails even when the origin sits in a warp well', () => {
    const ship = record({
      recordId: 'w1-orbit',
      lastSeen: { turn: 9, x: 1001, y: 2000 },
      motion: {
        heading: 90,
        warp: 1,
        travelLyPerTurn: 1,
        trailStop: { x: 1100, y: 2000 },
      },
    })
    const planets = [planetStop(1000, 2000)]
    const segments = fleetHeadingTrailSegmentsFromRecord(ship, 1, 9, 3, planets)
    expect(segments.some((s) => s.turnOffset < 0)).toBe(true)
    const back = segments.find((s) => s.turnOffset === -1)!
    expect(back.x).toBeCloseTo(1000)
    expect(back.endX).toBeCloseTo(1001)
  })

  it('omits back-trails when the origin is already in a warp well', () => {
    const ship = record({
      recordId: 'orbit',
      lastSeen: { turn: 9, x: 1001, y: 2000 },
      motion: {
        heading: 90,
        warp: 5,
        travelLyPerTurn: 25,
        trailStop: { x: 2000, y: 2000 },
      },
    })
    const planets = [planetStop(1000, 2000)]
    const segments = fleetHeadingTrailSegmentsFromRecord(ship, 1, 9, 3, planets)
    expect(segments.every((s) => s.turnOffset >= 0)).toBe(true)
    expect(segments.some((s) => s.turnOffset < 0)).toBe(false)
  })

  it('stops back-trails at a planet well behind the ship', () => {
    const ship = record({
      recordId: 'back',
      lastSeen: { turn: 9, x: 1000, y: 2000 },
      motion: {
        heading: 90,
        warp: 5,
        travelLyPerTurn: 25,
        trailStop: { x: 2000, y: 2000 },
      },
    })
    // Planet west of origin; back ray hits exact planet on a later segment.
    const planets = [planetStop(950, 2000)]
    const segments = fleetHeadingTrailSegmentsFromRecord(ship, 1, 9, 3, planets)
    const backward = segments
      .filter((s) => s.turnOffset < 0)
      .sort((a, b) => b.turnOffset - a.turnOffset)
    expect(backward.length).toBeGreaterThanOrEqual(1)
    expect(backward.length).toBeLessThanOrEqual(2)
    const last = backward[backward.length - 1]!
    expect(last.x).toBe(950)
    expect(last.y).toBe(2000)
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
