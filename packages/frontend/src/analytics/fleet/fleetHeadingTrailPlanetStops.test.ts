import { describe, expect, it } from 'vitest'
import {
  firstFleetTrailPlanetStopAlongSegment,
  FLEET_TRAIL_NORMAL_WARP_WELL_RADIUS,
  pointInAnyFleetTrailPlanetStop,
  type FleetTrailPlanetStop,
} from './fleetHeadingTrailPlanetStops'
import { fleetTrailPlanetStopsFromMapNodes } from './fleetTrailPlanetStopsFromMapNodes'

describe('fleetHeadingTrailPlanetStops', () => {
  const planet: FleetTrailPlanetStop = {
    x: 1000,
    y: 2000,
    stopRadius: FLEET_TRAIL_NORMAL_WARP_WELL_RADIUS,
  }

  it('detects points inside the normal well', () => {
    expect(pointInAnyFleetTrailPlanetStop(1000, 2000, [planet])).toBe(true)
    expect(pointInAnyFleetTrailPlanetStop(1003, 2000, [planet])).toBe(true)
    expect(pointInAnyFleetTrailPlanetStop(1004, 2000, [planet])).toBe(false)
  })

  it('finds the first well entry along a segment and returns the planet center', () => {
    const hit = firstFleetTrailPlanetStopAlongSegment(
      1100,
      2000,
      900,
      2000,
      [planet],
      { skipPlanetsContainingStart: true }
    )
    expect(hit).toEqual({ x: 1000, y: 2000, distanceAlong: 97 })
  })

  it('skips the well that already contains the start when departing', () => {
    const hit = firstFleetTrailPlanetStopAlongSegment(
      1001,
      2000,
      1100,
      2000,
      [planet],
      { skipPlanetsContainingStart: true }
    )
    expect(hit).toBeNull()
  })
})

describe('fleetTrailPlanetStopsFromMapNodes', () => {
  it('uses well radius 3 when normalWellCells are present', () => {
    const stops = fleetTrailPlanetStopsFromMapNodes([
      {
        x: 10,
        y: 20,
        planet: { id: 1, debrisdisk: 0 },
        normalWellCells: [{ x: 10, y: 20 }],
      },
    ])
    expect(stops).toEqual([{ x: 10, y: 20, stopRadius: 3 }])
  })

  it('uses cell radius when normalWellCells are empty (debris)', () => {
    const stops = fleetTrailPlanetStopsFromMapNodes([
      {
        x: 10,
        y: 20,
        planet: { id: 1, debrisdisk: 1 },
        normalWellCells: [],
      },
    ])
    expect(stops).toEqual([{ x: 10, y: 20, stopRadius: 0.5 }])
  })
})
