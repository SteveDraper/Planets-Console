import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  buildMapRegionOverlayPaneShapes,
  parseCssColorToRgb,
  patchRasterDataUrl,
} from './mapRegionOverlay'
import type { MapRegionOverlay, MapRegionOverlayPatch } from '../api/mapRegionOverlayTypes'

function mockCanvas2d() {
  let written: Uint8ClampedArray | null = null
  const mockCtx = {
    createImageData: (w: number, h: number) => ({
      data: new Uint8ClampedArray(w * h * 4),
    }),
    putImageData: (image: ImageData) => {
      written = new Uint8ClampedArray(image.data)
    },
  }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    mockCtx as unknown as CanvasRenderingContext2D
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(
    'data:image/png;base64,mock'
  )
  return () => written
}

function patchAabbsOverlap(
  a: Pick<MapRegionOverlayPatch, 'originX' | 'originY' | 'width' | 'height'>,
  b: Pick<MapRegionOverlayPatch, 'originX' | 'originY' | 'width' | 'height'>
): boolean {
  const aMaxX = a.originX + a.width - 1
  const aMaxY = a.originY + a.height - 1
  const bMaxX = b.originX + b.width - 1
  const bMaxY = b.originY + b.height - 1
  return !(aMaxX < b.originX || bMaxX < a.originX || aMaxY < b.originY || bMaxY < a.originY)
}

describe('buildMapRegionOverlayPaneShapes', () => {
  const viewport = { width: 800, height: 600, tx: 0, ty: 0, scale: 1 }

  beforeEach(() => {
    mockCanvas2d()
  })

  it('projects disks and cached patches without recompositing the full map', () => {
    const overlay: MapRegionOverlay = {
      kind: 'demo',
      id: 'demo-1',
      fillColor: '#22c55e',
      fillOpacity: 0.25,
      disks: [
        { x: 10, y: 20, radius: 50 },
        { x: 40, y: 20, radius: 50 },
      ],
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

    const first = buildMapRegionOverlayPaneShapes([overlay], viewport)
    const second = buildMapRegionOverlayPaneShapes([overlay], {
      ...viewport,
      tx: 100,
      scale: 2,
    })

    expect(first.groups).toHaveLength(1)
    expect(first.groups[0]!.disks).toHaveLength(2)
    expect(first.groups[0]!.patches).toHaveLength(1)
    expect(first.groups[0]!.patchMaskRects).toHaveLength(1)
    expect(second.groups[0]!.patches[0]!.imageDataUrl).toBe(
      first.groups[0]!.patches[0]!.imageDataUrl
    )
    expect(second.groups[0]!.disks[0]!.cx).not.toBe(first.groups[0]!.disks[0]!.cx)
  })

  it('emits disk-only groups with no patch work', () => {
    const overlay: MapRegionOverlay = {
      kind: 'demo',
      id: 'demo-2',
      fillColor: '#22c55e',
      fillOpacity: 0.25,
      disks: [{ x: 0, y: 0, radius: 100 }],
      patches: [],
    }
    const shapes = buildMapRegionOverlayPaneShapes([overlay], viewport)
    expect(shapes.groups[0]!.disks).toHaveLength(1)
    expect(shapes.groups[0]!.patches).toEqual([])
  })

  it('keeps patch mask rects non-overlapping for partitioned patch AABBs', () => {
    const west: MapRegionOverlayPatch = {
      originX: 0,
      originY: 0,
      width: 10,
      height: 10,
      coverageRle: [{ length: 100, covered: true }],
    }
    const east: MapRegionOverlayPatch = {
      originX: 20,
      originY: 0,
      width: 10,
      height: 10,
      coverageRle: [{ length: 100, covered: true }],
    }
    expect(patchAabbsOverlap(west, east)).toBe(false)

    const overlay: MapRegionOverlay = {
      kind: 'demo',
      id: 'demo-partition',
      fillColor: '#22c55e',
      fillOpacity: 0.25,
      disks: [{ x: 0, y: 0, radius: 100 }],
      patches: [west, east],
    }
    const shapes = buildMapRegionOverlayPaneShapes([overlay], viewport)
    const rects = shapes.groups[0]!.patchMaskRects
    expect(rects).toHaveLength(2)
    const [a, b] = rects
    expect(
      !(
        a!.x + a!.width <= b!.x ||
        b!.x + b!.width <= a!.x ||
        a!.y + a!.height <= b!.y ||
        b!.y + b!.height <= a!.y
      )
    ).toBe(false)
    expect(shapes.groups[0]!.patches).toHaveLength(2)
  })

  it('skips patch punch and raster when fillColor is not hex', () => {
    const overlay: MapRegionOverlay = {
      kind: 'demo',
      id: 'demo-bad-color',
      fillColor: 'rgb(34, 197, 94)',
      fillOpacity: 0.25,
      disks: [{ x: 0, y: 0, radius: 50 }],
      patches: [
        {
          originX: 0,
          originY: 0,
          width: 1,
          height: 1,
          coverageRle: [{ length: 1, covered: true }],
        },
      ],
    }
    const shapes = buildMapRegionOverlayPaneShapes([overlay], viewport)
    expect(shapes.groups[0]!.disks).toHaveLength(1)
    expect(shapes.groups[0]!.patches).toEqual([])
    expect(shapes.groups[0]!.patchMaskRects).toEqual([])
  })
})

describe('parseCssColorToRgb', () => {
  it('parses hex and rejects unsupported colors', () => {
    expect(parseCssColorToRgb('#112233')).toEqual({ r: 17, g: 34, b: 51 })
    expect(parseCssColorToRgb('#abc')).toEqual({ r: 170, g: 187, b: 204 })
    expect(parseCssColorToRgb('green')).toBeNull()
    expect(parseCssColorToRgb('rgb(1,2,3)')).toBeNull()
  })
})

describe('patchRasterDataUrl', () => {
  it('flips map-south RLE rows to image-top and caches by patch identity', () => {
    const getWritten = mockCanvas2d()
    const patch = {
      originX: 0,
      originY: 0,
      width: 1,
      height: 2,
      coverageRle: [
        { length: 1, covered: true },
        { length: 1, covered: false },
      ],
    }

    const urlA = patchRasterDataUrl('#112233', patch)
    const written = getWritten()
    expect(urlA).toContain('data:image/png')
    expect(written).not.toBeNull()
    expect(written![3]).toBe(0)
    expect(written![7]).toBe(255)

    const toDataURL = vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL')
    const urlB = patchRasterDataUrl('#112233', patch)
    expect(urlB).toBe(urlA)
    expect(toDataURL).not.toHaveBeenCalled()
  })

  it('returns empty string for non-hex fillColor', () => {
    mockCanvas2d()
    const patch = {
      originX: 0,
      originY: 0,
      width: 1,
      height: 1,
      coverageRle: [{ length: 1, covered: true }],
    }
    expect(patchRasterDataUrl('not-a-color', patch)).toBe('')
  })
})
