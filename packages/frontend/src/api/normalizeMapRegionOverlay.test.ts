import { describe, expect, it } from 'vitest'
import { normalizeMapRegionOverlay, normalizeMapRegionOverlays } from './normalizeMapRegionOverlay'
import { normalizeMapDataResponse } from './normalizeMapDataResponse'

describe('normalizeMapRegionOverlay', () => {
  const validCoverage = {
    kind: 'demo',
    id: 'demo-1',
    fillColor: '#22c55e',
    fillOpacity: 0.25,
    geometry: {
      type: 'coverage' as const,
      disks: [{ x: 10, y: 20, radius: 50 }],
      patches: [
        {
          originX: 0,
          originY: 0,
          width: 2,
          height: 2,
          coverageRle: [
            { length: 2, covered: true },
            { length: 2, covered: false },
          ],
        },
      ],
    },
  }

  const validBoundary = {
    kind: 'homeworld-sector',
    id: 'sector-0',
    fillColor: '#f97316',
    fillOpacity: 0.2,
    geometry: {
      type: 'boundary' as const,
      vertices: [
        { x: 200, y: 0 },
        { x: 0, y: 200 },
        { x: 0, y: 100 },
        { x: 100, y: 0 },
      ],
      edges: [
        { type: 'arc' as const, centerX: 0, centerY: 0, clockwise: false },
        { type: 'line' as const },
        { type: 'arc' as const, centerX: 0, centerY: 0, clockwise: true },
        { type: 'line' as const },
      ],
      disks: [{ x: 150, y: 50, radius: 81 }],
    },
    isPinned: true,
    status: 'ok',
    hoverSummary: 'pinned sector',
  }

  it('accepts a well-formed coverage overlay', () => {
    expect(normalizeMapRegionOverlay(validCoverage)).toEqual(validCoverage)
  })

  it('accepts a well-formed boundary overlay with annotations', () => {
    expect(normalizeMapRegionOverlay(validBoundary)).toEqual(validBoundary)
  })

  it('accepts legacy flat disks+patches as coverage', () => {
    expect(
      normalizeMapRegionOverlay({
        kind: 'demo',
        id: 'legacy-1',
        fillColor: '#22c55e',
        fillOpacity: 0.25,
        disks: [{ x: 10, y: 20, radius: 50 }],
        patches: [],
      })
    ).toEqual({
      kind: 'demo',
      id: 'legacy-1',
      fillColor: '#22c55e',
      fillOpacity: 0.25,
      geometry: {
        type: 'coverage',
        disks: [{ x: 10, y: 20, radius: 50 }],
        patches: [],
      },
    })
  })

  it('rejects RLE that does not match patch size', () => {
    expect(
      normalizeMapRegionOverlay({
        ...validCoverage,
        geometry: {
          ...validCoverage.geometry,
          patches: [
            {
              originX: 0,
              originY: 0,
              width: 2,
              height: 2,
              coverageRle: [{ length: 1, covered: true }],
            },
          ],
        },
      })
    ).toBeNull()
  })

  it('rejects boundary with mismatched edge/vertex counts', () => {
    expect(
      normalizeMapRegionOverlay({
        ...validBoundary,
        geometry: {
          ...validBoundary.geometry,
          edges: [{ type: 'line' }],
        },
      })
    ).toBeNull()
  })

  it('rejects boundary with fewer than 3 vertices', () => {
    expect(
      normalizeMapRegionOverlay({
        ...validBoundary,
        geometry: {
          type: 'boundary',
          vertices: [
            { x: 0, y: 0 },
            { x: 1, y: 0 },
          ],
          edges: [
            { type: 'line' },
            { type: 'line' },
          ],
        },
      })
    ).toBeNull()
  })

  it('rejects invalid arc edges', () => {
    expect(
      normalizeMapRegionOverlay({
        ...validBoundary,
        geometry: {
          ...validBoundary.geometry,
          edges: [
            { type: 'arc', centerX: 0, centerY: 0 },
            { type: 'line' },
            { type: 'arc', centerX: 0, centerY: 0, clockwise: true },
            { type: 'line' },
          ],
        },
      })
    ).toBeNull()
  })

  it('rejects non-boolean isPinned when present', () => {
    expect(normalizeMapRegionOverlay({ ...validBoundary, isPinned: 'yes' })).toBeNull()
  })

  it('normalizes regionOverlays on map data responses', () => {
    const out = normalizeMapDataResponse({
      analyticId: 'visibility',
      nodes: [],
      edges: [],
      regionOverlays: [validCoverage],
    })
    expect(out.regionOverlays).toEqual([validCoverage])
  })

  it('filters invalid overlays from a list', () => {
    expect(normalizeMapRegionOverlays([validCoverage, { kind: 'x' }, null])).toEqual([
      validCoverage,
    ])
  })
})
