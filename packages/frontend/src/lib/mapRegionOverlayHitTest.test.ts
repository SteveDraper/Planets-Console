import { describe, expect, it } from 'vitest'
import type {
  MapRegionBoundaryGeometry,
  MapRegionOverlay,
} from '../api/mapRegionOverlayTypes'
import {
  boundaryGeometryToPolyline,
  collectRegionOverlayHoverSummaries,
  pointInBoundaryGeometry,
  pointInDisk,
  pointHitsMapRegionOverlay,
} from './mapRegionOverlayHitTest'
import { formatHomeworldSectorHoverLine } from '../analytics/homeworld-locator/formatHomeworldSectorHover'

/** Quarter wedge in +X/+Y: angles 0 → π/2, r_inner=100, r_outer=200, center origin. */
function annularSectorGeometry(
  overrides: Partial<MapRegionBoundaryGeometry> = {}
): MapRegionBoundaryGeometry {
  return {
    type: 'boundary',
    vertices: [
      { x: 200, y: 0 },
      { x: 0, y: 200 },
      { x: 0, y: 100 },
      { x: 100, y: 0 },
    ],
    edges: [
      { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
      { type: 'line' },
      { type: 'arc', centerX: 0, centerY: 0, clockwise: true },
      { type: 'line' },
    ],
    disks: [{ x: 150, y: 50, radius: 81 }],
    ...overrides,
  }
}

function annularSectorOverlay(overrides: Partial<MapRegionOverlay> = {}): MapRegionOverlay {
  return {
    kind: 'homeworld-sector',
    id: 'sector-0',
    fillColor: '#f97316',
    fillOpacity: 0.2,
    isPinned: false,
    status: 'ok',
    candidateCount: 3,
    geometry: annularSectorGeometry(),
    ...overrides,
  }
}

/** Same annular sector starting at the inner radial (rotated edge order). */
function annularSectorRotatedGeometry(): MapRegionBoundaryGeometry {
  return {
    type: 'boundary',
    vertices: [
      { x: 0, y: 100 },
      { x: 100, y: 0 },
      { x: 200, y: 0 },
      { x: 0, y: 200 },
    ],
    edges: [
      { type: 'arc', centerX: 0, centerY: 0, clockwise: true },
      { type: 'line' },
      { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
      { type: 'line' },
    ],
  }
}

describe('mapRegionOverlayHitTest', () => {
  it('hits annular sector interior and misses outside band/wedge', () => {
    const geometry = annularSectorGeometry()
    expect(pointInBoundaryGeometry(150, 50, geometry)).toBe(true)
    expect(pointInBoundaryGeometry(50, 0, geometry)).toBe(false) // inside r_inner
    expect(pointInBoundaryGeometry(250, 0, geometry)).toBe(false) // outside r_outer
    expect(pointInBoundaryGeometry(150, -50, geometry)).toBe(false) // wrong wedge
  })

  it('hits the same annular sector when edge order is rotated', () => {
    const geometry = annularSectorRotatedGeometry()
    expect(pointInBoundaryGeometry(150, 50, geometry)).toBe(true)
    expect(pointInBoundaryGeometry(50, 0, geometry)).toBe(false)
    expect(pointInBoundaryGeometry(250, 0, geometry)).toBe(false)
    expect(pointInBoundaryGeometry(150, -50, geometry)).toBe(false)
  })

  it('hits a line-only closed polygon independent of vertex start', () => {
    const square: MapRegionBoundaryGeometry = {
      type: 'boundary',
      vertices: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 10 },
        { x: 0, y: 10 },
      ],
      edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }, { type: 'line' }],
    }
    const squareRotated: MapRegionBoundaryGeometry = {
      type: 'boundary',
      vertices: [
        { x: 10, y: 10 },
        { x: 0, y: 10 },
        { x: 0, y: 0 },
        { x: 10, y: 0 },
      ],
      edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }, { type: 'line' }],
    }
    expect(pointInBoundaryGeometry(5, 5, square)).toBe(true)
    expect(pointInBoundaryGeometry(5, 5, squareRotated)).toBe(true)
    expect(pointInBoundaryGeometry(15, 5, square)).toBe(false)
    expect(pointInBoundaryGeometry(-1, 5, squareRotated)).toBe(false)
  })

  it('hits a disk sector (pie slice: two radials + outer arc)', () => {
    // Quarter disk at origin: 0 → π/2, r=100.
    const geometry: MapRegionBoundaryGeometry = {
      type: 'boundary',
      vertices: [
        { x: 0, y: 0 },
        { x: 100, y: 0 },
        { x: 0, y: 100 },
      ],
      edges: [
        { type: 'line' },
        { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
        { type: 'line' },
      ],
    }
    expect(pointInBoundaryGeometry(40, 40, geometry)).toBe(true)
    expect(pointInBoundaryGeometry(40, -40, geometry)).toBe(false)
    expect(pointInBoundaryGeometry(120, 40, geometry)).toBe(false)
  })

  it('flattens arcs into a polyline with more than the corner vertices', () => {
    const ring = boundaryGeometryToPolyline(annularSectorGeometry({ disks: undefined }))
    expect(ring).not.toBeNull()
    // Four corners alone would be length 4; quarter arcs need intermediate samples.
    expect(ring!.length).toBeGreaterThan(4)
  })

  it('hits envelope disks', () => {
    expect(pointInDisk(150, 50, { x: 150, y: 50, radius: 81 })).toBe(true)
    expect(pointInDisk(150, 50 + 82, { x: 150, y: 50, radius: 81 })).toBe(false)
  })

  it('collects formatted hover lines for hit overlays only', () => {
    const hit = annularSectorOverlay({
      id: 'hit',
      isPinned: true,
      candidateCount: 1,
      playerLabel: 'alice',
    })
    const miss = annularSectorOverlay({
      id: 'miss',
      status: 'error',
      candidateCount: 0,
      geometry: {
        type: 'boundary',
        vertices: [
          { x: -200, y: 0 },
          { x: 0, y: -200 },
          { x: 0, y: -100 },
          { x: -100, y: 0 },
        ],
        edges: [
          { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
          { type: 'line' },
          { type: 'arc', centerX: 0, centerY: 0, clockwise: true },
          { type: 'line' },
        ],
      },
    })
    const noHover = annularSectorOverlay({
      id: 'bare',
      kind: 'visibility-ship-scan',
      candidateCount: undefined,
      status: undefined,
    })

    expect(
      collectRegionOverlayHoverSummaries(
        [hit, miss, noHover],
        150,
        50,
        formatHomeworldSectorHoverLine
      )
    ).toEqual(['player: alice · 1 candidate'])
    expect(pointHitsMapRegionOverlay(150, 50, hit)).toBe(true)
    expect(pointHitsMapRegionOverlay(150, 50, miss)).toBe(false)
  })

  it('hits via envelope disk even outside the annular wedge', () => {
    const overlay = annularSectorOverlay({
      status: 'incomplete',
      candidateCount: 0,
      geometry: {
        type: 'boundary',
        vertices: [
          { x: 200, y: 0 },
          { x: 0, y: 200 },
          { x: 0, y: 100 },
          { x: 100, y: 0 },
        ],
        edges: [
          { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
          { type: 'line' },
          { type: 'arc', centerX: 0, centerY: 0, clockwise: true },
          { type: 'line' },
        ],
        // Disk centered well outside the +X/+Y wedge.
        disks: [{ x: -50, y: -50, radius: 20 }],
      },
    })
    expect(
      collectRegionOverlayHoverSummaries(
        [overlay],
        -50,
        -50,
        formatHomeworldSectorHoverLine
      )
    ).toEqual(['incomplete scan · 0 candidates'])
  })

  it('hits coverage disks', () => {
    const overlay: MapRegionOverlay = {
      kind: 'visibility',
      id: 'vis-1',
      fillColor: '#0ea5e9',
      fillOpacity: 0.15,
      geometry: {
        type: 'coverage',
        disks: [{ x: 10, y: 20, radius: 5 }],
        patches: [],
      },
    }
    expect(pointHitsMapRegionOverlay(10, 20, overlay)).toBe(true)
    expect(pointHitsMapRegionOverlay(20, 20, overlay)).toBe(false)
  })
})
