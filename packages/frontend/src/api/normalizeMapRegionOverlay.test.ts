import { describe, expect, it } from 'vitest'
import { normalizeMapRegionOverlay, normalizeMapRegionOverlays } from './normalizeMapRegionOverlay'
import { normalizeMapDataResponse } from './normalizeMapDataResponse'

describe('normalizeMapRegionOverlay', () => {
  const validOverlay = {
    kind: 'demo',
    id: 'demo-1',
    fillColor: '#22c55e',
    fillOpacity: 0.25,
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
  }

  it('accepts a well-formed overlay', () => {
    expect(normalizeMapRegionOverlay(validOverlay)).toEqual(validOverlay)
  })

  it('rejects RLE that does not match patch size', () => {
    expect(
      normalizeMapRegionOverlay({
        ...validOverlay,
        patches: [
          {
            originX: 0,
            originY: 0,
            width: 2,
            height: 2,
            coverageRle: [{ length: 1, covered: true }],
          },
        ],
      })
    ).toBeNull()
  })

  it('normalizes regionOverlays on map data responses', () => {
    const out = normalizeMapDataResponse({
      analyticId: 'map-region-demo',
      nodes: [],
      edges: [],
      regionOverlays: [validOverlay],
    })
    expect(out.regionOverlays).toEqual([validOverlay])
  })

  it('filters invalid overlays from a list', () => {
    expect(normalizeMapRegionOverlays([validOverlay, { kind: 'x' }, null])).toEqual([
      validOverlay,
    ])
  })
})
