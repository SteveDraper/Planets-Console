import { describe, expect, it } from 'vitest'
import {
  isCoordinateInWarpWell,
  mapCellsWithCenterInNormalWarpWell,
  normalWarpWellGridSegmentsFlow,
  planetIsInDebrisDisk,
  warpWellCartesianDistance,
} from './warpWell'

describe('planetIsInDebrisDisk', () => {
  it('is false when debrisdisk is 0 or missing', () => {
    expect(planetIsInDebrisDisk(undefined)).toBe(false)
    expect(planetIsInDebrisDisk({ debrisdisk: 0 })).toBe(false)
  })

  it('is true when debrisdisk is non-zero', () => {
    expect(planetIsInDebrisDisk({ debrisdisk: 1 })).toBe(true)
  })
})

describe('isCoordinateInWarpWell', () => {
  const planet = { debrisdisk: 0 }

  it('normal well includes Cartesian distance 3', () => {
    expect(isCoordinateInWarpWell(10, 20, planet, 13, 20, 'normal')).toBe(true)
    expect(isCoordinateInWarpWell(10, 20, planet, 10, 23, 'normal')).toBe(true)
  })

  it('normal well excludes distance beyond 3', () => {
    expect(isCoordinateInWarpWell(10, 20, planet, 14, 20, 'normal')).toBe(false)
    expect(isCoordinateInWarpWell(10, 20, planet, 10, 24, 'normal')).toBe(false)
  })

  it('hyperjump well excludes distance 3', () => {
    expect(isCoordinateInWarpWell(10, 20, planet, 13, 20, 'hyperjump')).toBe(false)
    expect(isCoordinateInWarpWell(10, 20, planet, 12, 20, 'hyperjump')).toBe(true)
  })

  it('returns false for debris-disk planets', () => {
    expect(isCoordinateInWarpWell(10, 20, { debrisdisk: 1 }, 10, 20, 'normal')).toBe(false)
  })
})

describe('mapCellsWithCenterInNormalWarpWell', () => {
  it('returns empty for non-finite planet position', () => {
    expect(mapCellsWithCenterInNormalWarpWell(NaN, 0)).toEqual([])
  })

  it('includes the planet cell and excludes cells beyond radius 3', () => {
    const cells = mapCellsWithCenterInNormalWarpWell(0, 0)
    const has = (gx: number, gy: number) => cells.some((c) => c.gx === gx && c.gy === gy)
    expect(has(0, 0)).toBe(true)
    expect(has(3, 0)).toBe(true)
    expect(has(4, 0)).toBe(false)
    expect(has(2, 2)).toBe(true)
    expect(has(3, 2)).toBe(false)
  })
})

describe('normalWarpWellGridSegmentsFlow', () => {
  it('returns axis-aligned segments on integer grid lines', () => {
    const segs = normalWarpWellGridSegmentsFlow(10, 20)
    expect(segs.length).toBeGreaterThan(0)
    for (const s of segs) {
      expect(s.x1 === s.x2 || s.y1 === s.y2).toBe(true)
      expect(Number.isInteger(s.x1) && Number.isInteger(s.x2)).toBe(true)
      expect(Number.isInteger(s.y1) && Number.isInteger(s.y2)).toBe(true)
    }
  })

  it('includes interior edges between adjacent well cells (not only outer hull)', () => {
    const segs = normalWarpWellGridSegmentsFlow(0, 0)
    const hasSharedWall = segs.some(
      (s) =>
        s.x1 === s.x2 &&
        s.x1 === 0 &&
        Math.min(s.y1, s.y2) === -1 &&
        Math.max(s.y1, s.y2) === 0
    )
    expect(hasSharedWall).toBe(true)
  })

  it('returns more segments than the outer boundary alone', () => {
    const full = normalWarpWellGridSegmentsFlow(0, 0).length
    expect(full).toBeGreaterThan(40)
  })

  it('returns empty for non-finite planet position', () => {
    expect(normalWarpWellGridSegmentsFlow(NaN, 0)).toEqual([])
  })
})

describe('warpWellCartesianDistance', () => {
  it('matches hypot', () => {
    expect(warpWellCartesianDistance(0, 0, 3, 4)).toBe(5)
    expect(warpWellCartesianDistance(0, 0, -3, 0)).toBe(3)
  })
})
