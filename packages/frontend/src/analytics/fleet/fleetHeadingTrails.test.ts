import { describe, expect, it } from 'vitest'
import { headingTravelDeltaGameLy } from '../../lib/cartography/ionStormMovement'
import {
  collectFleetHeadingTrails,
  fleetHeadingTrailEndpoint,
  fleetHeadingTrailFromRecord,
  FLEET_HEADING_TRAIL_CURRENT_OPACITY,
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
    })
    expect(end).toEqual({ x: 1000, y: 2025 })
  })

  it('moves east at heading 90', () => {
    const end = fleetHeadingTrailEndpoint(1000, 2000, {
      heading: 90,
      warp: 3,
      travelLyPerTurn: 9,
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
          motion: { heading: 0, warp: 9, travelLyPerTurn: 81 },
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
        motion: { heading: 0, warp: 9, travelLyPerTurn: 81 },
      }),
      3,
      9
    )
    expect(trail).toEqual({
      key: 'r1:500,600',
      recordId: 'r1',
      playerId: 3,
      x: 500,
      y: 600,
      endX: 500,
      endY: 681,
      heading: 0,
      travelLyPerTurn: 81,
      opacity: FLEET_HEADING_TRAIL_CURRENT_OPACITY,
    })
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
              motion: { heading: 90, warp: 4, travelLyPerTurn: 16 },
            }),
            record({
              recordId: 'a-lost',
              disposition: 'lost',
              lastSeen: { turn: 9, x: 10, y: 20 },
              motion: { heading: 90, warp: 4, travelLyPerTurn: 16 },
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
              motion: { heading: 0, warp: 9, travelLyPerTurn: 81 },
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

    const trails = collectFleetHeadingTrails(byId, [{ playerId: 1, name: 'Alice' }], 9)
    expect(trails).toHaveLength(1)
    expect(trails[0]!.recordId).toBe('a-ok')
    expect(trails[0]!.playerId).toBe(1)
    const { dx, dy } = headingTravelDeltaGameLy(90, 16)
    expect(trails[0]!.endX).toBeCloseTo(10 + dx)
    expect(trails[0]!.endY).toBeCloseTo(20 + dy)
  })
})
