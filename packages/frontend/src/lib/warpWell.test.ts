import { describe, expect, it } from 'vitest'
import {
  flowBoundingBoxFromWellCells,
  flowBoundsIntersect,
  normalWellGridSegmentsFromCells,
  type WarpWellMapCell,
} from './warpWell'

const SAMPLE_CELLS: WarpWellMapCell[] = [
  { x: 0, y: 0 },
  { x: 1, y: 0 },
  { x: 0, y: 1 },
]

describe('normalWellGridSegmentsFromCells', () => {
  it('returns empty for missing or empty cells', () => {
    expect(normalWellGridSegmentsFromCells(undefined)).toEqual([])
    expect(normalWellGridSegmentsFromCells([])).toEqual([])
  })

  it('returns axis-aligned segments on integer grid lines', () => {
    const segs = normalWellGridSegmentsFromCells(SAMPLE_CELLS)
    expect(segs.length).toBeGreaterThan(0)
    for (const s of segs) {
      expect(s.x1 === s.x2 || s.y1 === s.y2).toBe(true)
      expect(Number.isInteger(s.x1) && Number.isInteger(s.x2)).toBe(true)
      expect(Number.isInteger(s.y1) && Number.isInteger(s.y2)).toBe(true)
    }
  })

  it('deduplicates shared edges between adjacent cells', () => {
    const segs = normalWellGridSegmentsFromCells(SAMPLE_CELLS)
    const hasSharedWall = segs.some(
      (s) =>
        s.x1 === s.x2 &&
        s.x1 === 1 &&
        Math.min(s.y1, s.y2) === -1 &&
        Math.max(s.y1, s.y2) === 0
    )
    expect(hasSharedWall).toBe(true)
  })

  it('drops cells with non-numeric, non-finite, or non-integer coordinates (no coercion)', () => {
    const segs = normalWellGridSegmentsFromCells([
      { x: 0, y: 0 },
      { x: '1', y: 0 },
      { x: 1, y: Number.NaN },
      { x: 1.5, y: 0 },
      { x: 1, y: 0 },
    ])
    expect(segs.length).toBeGreaterThan(0)
    expect(normalWellGridSegmentsFromCells([{ x: '0', y: 0 }])).toEqual([])
    expect(normalWellGridSegmentsFromCells([{ x: 0.5, y: 0 }])).toEqual([])
  })
})

describe('flowBoundingBoxFromWellCells', () => {
  it('returns null for empty cells', () => {
    expect(flowBoundingBoxFromWellCells([])).toBeNull()
  })

  it('contains every endpoint of normalWellGridSegmentsFromCells', () => {
    const box = flowBoundingBoxFromWellCells(SAMPLE_CELLS)
    expect(box).not.toBeNull()
    const segs = normalWellGridSegmentsFromCells(SAMPLE_CELLS)
    for (const s of segs) {
      for (const v of [s.x1, s.x2, s.y1, s.y2]) {
        expect(Number.isFinite(v)).toBe(true)
      }
      expect(s.x1).toBeGreaterThanOrEqual(box!.flowXMin)
      expect(s.x1).toBeLessThanOrEqual(box!.flowXMax)
      expect(s.x2).toBeGreaterThanOrEqual(box!.flowXMin)
      expect(s.x2).toBeLessThanOrEqual(box!.flowXMax)
      expect(s.y1).toBeGreaterThanOrEqual(box!.flowYMin)
      expect(s.y1).toBeLessThanOrEqual(box!.flowYMax)
      expect(s.y2).toBeGreaterThanOrEqual(box!.flowYMin)
      expect(s.y2).toBeLessThanOrEqual(box!.flowYMax)
    }
  })
})

describe('flowBoundsIntersect', () => {
  it('is true when viewport overlaps the well box', () => {
    const box = flowBoundingBoxFromWellCells(SAMPLE_CELLS)!
    expect(flowBoundsIntersect(box, -1, 3, -3, 0)).toBe(true)
  })

  it('is false when viewport is disjoint', () => {
    const box = flowBoundingBoxFromWellCells(SAMPLE_CELLS)!
    expect(flowBoundsIntersect(box, 500, 600, -3, 0)).toBe(false)
  })
})
