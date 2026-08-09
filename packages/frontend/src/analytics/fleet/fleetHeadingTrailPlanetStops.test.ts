import { describe, expect, it } from 'vitest'
import type { WarpWellMapCell } from '../../lib/warpWell'
import {
  firstFleetTrailPlanetStopAlongSegment,
  pointInAnyFleetTrailPlanetStop,
  type FleetTrailPlanetStop,
} from './fleetHeadingTrailPlanetStops'
import { fleetTrailPlanetStopsFromMapNodes } from './fleetTrailPlanetStopsFromMapNodes'

/** Test fixture mirroring Core ``map_cell_indices_in_warp_well`` for NORMAL wells. */
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

describe('fleetHeadingTrailPlanetStops', () => {
  const planet: FleetTrailPlanetStop = {
    x: 1000,
    y: 2000,
    wellCells: normalWellCellsAround(1000, 2000),
  }

  it('detects points whose map cell is in the shipped well', () => {
    expect(pointInAnyFleetTrailPlanetStop(1000, 2000, [planet])).toBe(true)
    expect(pointInAnyFleetTrailPlanetStop(1003, 2000, [planet])).toBe(true)
    expect(pointInAnyFleetTrailPlanetStop(1004, 2000, [planet])).toBe(false)
  })

  it('finds an exact planet hit along a segment and returns the planet center', () => {
    const hit = firstFleetTrailPlanetStopAlongSegment(
      1100,
      2000,
      900,
      2000,
      [planet],
      { skipPlanetsContainingStart: true }
    )
    expect(hit).toEqual({ x: 1000, y: 2000, distanceAlong: 100 })
  })

  it('stops when the segment endpoint lands in a well cell (no mid-path disk)', () => {
    // Path misses the planet center but ends on a well cell east of the planet.
    const hit = firstFleetTrailPlanetStopAlongSegment(
      1003,
      2010,
      1003,
      2000,
      [planet],
      { skipPlanetsContainingStart: true }
    )
    expect(hit).toEqual({
      x: 1000,
      y: 2000,
      distanceAlong: Math.hypot(1000 - 1003, 2000 - 2010),
    })
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

  it('treats empty wellCells as planet-cell only', () => {
    const debris: FleetTrailPlanetStop = {
      x: 10,
      y: 20,
      wellCells: [],
    }
    expect(pointInAnyFleetTrailPlanetStop(10, 20, [debris])).toBe(true)
    expect(pointInAnyFleetTrailPlanetStop(10.4, 20.4, [debris])).toBe(true)
    expect(pointInAnyFleetTrailPlanetStop(11, 20, [debris])).toBe(false)
  })
})

describe('fleetTrailPlanetStopsFromMapNodes', () => {
  it('keeps shipped normalWellCells on the stop', () => {
    const cells = [{ x: 10, y: 20 }, { x: 11, y: 20 }]
    const stops = fleetTrailPlanetStopsFromMapNodes([
      {
        x: 10,
        y: 20,
        planet: { id: 1, debrisdisk: 0 },
        normalWellCells: cells,
      },
    ])
    expect(stops).toEqual([{ x: 10, y: 20, wellCells: cells }])
  })

  it('uses empty wellCells when normalWellCells are empty (debris)', () => {
    const stops = fleetTrailPlanetStopsFromMapNodes([
      {
        x: 10,
        y: 20,
        planet: { id: 1, debrisdisk: 1 },
        normalWellCells: [],
      },
    ])
    expect(stops).toEqual([{ x: 10, y: 20, wellCells: [] }])
  })

  it('does not invent well geometry when normalWellCells are missing', () => {
    const stops = fleetTrailPlanetStopsFromMapNodes([
      {
        x: 10,
        y: 20,
        planet: { id: 1, debrisdisk: 0 },
      },
    ])
    expect(stops).toEqual([{ x: 10, y: 20, wellCells: [] }])
  })
})
