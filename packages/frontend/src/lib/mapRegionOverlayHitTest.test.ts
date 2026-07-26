import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../api/mapRegionOverlayTypes'
import {
  angleInCounterClockwiseWedge,
  collectRegionOverlayHoverSummaries,
  pointInAnnularSectorBoundary,
  pointInDisk,
  pointHitsMapRegionOverlay,
} from './mapRegionOverlayHitTest'

function annularSectorOverlay(overrides: Partial<MapRegionOverlay> = {}): MapRegionOverlay {
  // Quarter wedge in +X/+Y: angles 0 → π/2, r_inner=100, r_outer=200, center origin.
  return {
    kind: 'homeworld-sector',
    id: 'sector-0',
    fillColor: '#f97316',
    fillOpacity: 0.2,
    isPinned: false,
    hoverSummary: '3 candidates',
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
      disks: [{ x: 150, y: 50, radius: 81 }],
    },
    ...overrides,
  }
}

describe('mapRegionOverlayHitTest', () => {
  it('checks CCW wedge membership', () => {
    expect(angleInCounterClockwiseWedge(Math.PI / 4, 0, Math.PI / 2)).toBe(true)
    expect(angleInCounterClockwiseWedge(-Math.PI / 4, 0, Math.PI / 2)).toBe(false)
    expect(angleInCounterClockwiseWedge(Math.PI, Math.PI / 2, (3 * Math.PI) / 2)).toBe(true)
  })

  it('hits annular sector interior and misses outside band/wedge', () => {
    const geometry = annularSectorOverlay().geometry
    if (geometry.type !== 'boundary') throw new Error('expected boundary')
    expect(pointInAnnularSectorBoundary(150, 50, geometry)).toBe(true)
    expect(pointInAnnularSectorBoundary(50, 0, geometry)).toBe(false) // inside r_inner
    expect(pointInAnnularSectorBoundary(250, 0, geometry)).toBe(false) // outside r_outer
    expect(pointInAnnularSectorBoundary(150, -50, geometry)).toBe(false) // wrong wedge
  })

  it('hits envelope disks', () => {
    expect(pointInDisk(150, 50, { x: 150, y: 50, radius: 81 })).toBe(true)
    expect(pointInDisk(150, 50 + 82, { x: 150, y: 50, radius: 81 })).toBe(false)
  })

  it('collects hoverSummary for hit overlays only', () => {
    const hit = annularSectorOverlay({ id: 'hit', hoverSummary: 'pinned · 1 candidate' })
    const miss = annularSectorOverlay({
      id: 'miss',
      hoverSummary: 'no candidates',
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
    const noSummary = annularSectorOverlay({ id: 'bare' })
    delete noSummary.hoverSummary

    expect(collectRegionOverlayHoverSummaries([hit, miss, noSummary], 150, 50)).toEqual([
      'pinned · 1 candidate',
    ])
    expect(pointHitsMapRegionOverlay(150, 50, hit)).toBe(true)
    expect(pointHitsMapRegionOverlay(150, 50, miss)).toBe(false)
  })

  it('hits via envelope disk even outside the annular wedge', () => {
    const overlay = annularSectorOverlay({
      hoverSummary: 'incomplete scan · 0 candidates',
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
    expect(collectRegionOverlayHoverSummaries([overlay], -50, -50)).toEqual([
      'incomplete scan · 0 candidates',
    ])
  })
})
