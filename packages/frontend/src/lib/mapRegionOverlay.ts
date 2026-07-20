/**
 * Pane shapes for hybrid map region overlays.
 *
 * Disks are SVG (opaque under one group opacity -- no alpha stacking, cheap on
 * pan/zoom). Nebula patches are small map-space PNGs cached by patch identity
 * and only reprojected each frame.
 */

import type { MapRegionOverlay } from '../api/mapRegionOverlayTypes'
import {
  flowToPane,
  gameMapCellCenterToFlow,
  mapLyToFlow,
  type CartographyOverlayViewport,
} from './cartography/cartographyOverlayGeometry'
import { flowLySpanToPanePixels } from './cartography/stellarCartographyOverlay'

export type MapRegionOverlayDiskShape = {
  key: string
  cx: number
  cy: number
  r: number
}

export type MapRegionOverlayPatchShape = {
  key: string
  left: number
  top: number
  width: number
  height: number
  imageDataUrl: string
}

export type MapRegionOverlayPaneGroup = {
  key: string
  fillColor: string
  fillOpacity: number
  disks: MapRegionOverlayDiskShape[]
  patches: MapRegionOverlayPatchShape[]
  /** Patch AABBs in pane px; punched from the disk-union mask. */
  patchMaskRects: { x: number; y: number; width: number; height: number }[]
}

export type MapRegionOverlayPaneShapes = {
  groups: MapRegionOverlayPaneGroup[]
}

type PatchRasterCacheEntry = {
  fillColor: string
  imageDataUrl: string
}

/** Weak cache keyed by patch object identity (stable across pan/zoom). */
const patchRasterCache = new WeakMap<object, PatchRasterCacheEntry>()

function expandCoverageRle(
  width: number,
  height: number,
  runs: readonly { length: number; covered: boolean }[]
): boolean[] {
  const expected = width * height
  const cells: boolean[] = []
  for (const run of runs) {
    for (let i = 0; i < run.length; i++) cells.push(run.covered)
  }
  if (cells.length !== expected) {
    throw new Error(`RLE length ${cells.length} does not match patch size ${expected}`)
  }
  return cells
}

/** Hex `#rgb` / `#rrggbb` only; null if the wire color is not a supported hex. */
export function parseCssColorToRgb(
  fillColor: string
): { r: number; g: number; b: number } | null {
  const hex = fillColor.trim()
  if (/^#[0-9a-fA-F]{6}$/.test(hex)) {
    return {
      r: parseInt(hex.slice(1, 3), 16),
      g: parseInt(hex.slice(3, 5), 16),
      b: parseInt(hex.slice(5, 7), 16),
    }
  }
  if (/^#[0-9a-fA-F]{3}$/.test(hex)) {
    return {
      r: parseInt(hex[1]! + hex[1]!, 16),
      g: parseInt(hex[2]! + hex[2]!, 16),
      b: parseInt(hex[3]! + hex[3]!, 16),
    }
  }
  return null
}

/**
 * Rasterize one nebula-local patch at 1 px/ly (map space).
 * RLE row 0 is map-south; canvas row 0 is image-top (map-north).
 * Returns empty string when fillColor is not a supported hex (fail closed).
 */
export function patchRasterDataUrl(
  fillColor: string,
  patch: MapRegionOverlay['patches'][number]
): string {
  const cached = patchRasterCache.get(patch)
  if (cached != null && cached.fillColor === fillColor) return cached.imageDataUrl

  if (typeof document === 'undefined') return ''
  const rgb = parseCssColorToRgb(fillColor)
  if (rgb == null) return ''
  const cells = expandCoverageRle(patch.width, patch.height, patch.coverageRle)
  const canvas = document.createElement('canvas')
  canvas.width = patch.width
  canvas.height = patch.height
  const ctx = canvas.getContext('2d')
  if (ctx == null) return ''
  const image = ctx.createImageData(patch.width, patch.height)
  const { r, g, b } = rgb
  for (let row = 0; row < patch.height; row++) {
    const sourceRow = patch.height - 1 - row
    for (let col = 0; col < patch.width; col++) {
      if (!cells[sourceRow * patch.width + col]) continue
      const offset = (row * patch.width + col) * 4
      image.data[offset] = r
      image.data[offset + 1] = g
      image.data[offset + 2] = b
      image.data[offset + 3] = 255
    }
  }
  ctx.putImageData(image, 0, 0)
  const imageDataUrl = canvas.toDataURL('image/png')
  patchRasterCache.set(patch, { fillColor, imageDataUrl })
  return imageDataUrl
}

function patchPaneRect(
  patch: MapRegionOverlay['patches'][number],
  viewport: CartographyOverlayViewport
): { left: number; top: number; width: number; height: number } {
  const { cx: leftGx, cy: topCy } = mapLyToFlow(
    patch.originX,
    patch.originY + patch.height
  )
  const { cx: rightGx, cy: bottomCy } = mapLyToFlow(
    patch.originX + patch.width,
    patch.originY
  )
  const topLeft = flowToPane(leftGx, topCy, viewport)
  const bottomRight = flowToPane(rightGx, bottomCy, viewport)
  const left = Math.min(topLeft.px, bottomRight.px)
  const top = Math.min(topLeft.py, bottomRight.py)
  const width = Math.abs(bottomRight.px - topLeft.px)
  const height = Math.abs(bottomRight.py - topLeft.py)
  return { left, top, width, height }
}

/**
 * Project overlays into pane shapes. Expensive patch PNGs are cached; each call
 * only recomputes pane positions from the viewport.
 */
export function buildMapRegionOverlayPaneShapes(
  overlays: readonly MapRegionOverlay[],
  viewport: CartographyOverlayViewport
): MapRegionOverlayPaneShapes {
  const groups: MapRegionOverlayPaneGroup[] = []

  for (const overlay of overlays) {
    const disks: MapRegionOverlayDiskShape[] = []
    const patches: MapRegionOverlayPatchShape[] = []
    const patchMaskRects: MapRegionOverlayPaneGroup['patchMaskRects'] = []

    for (let i = 0; i < overlay.disks.length; i++) {
      const disk = overlay.disks[i]!
      const { cx, cy } = gameMapCellCenterToFlow(disk.x, disk.y)
      const { px, py } = flowToPane(cx, cy, viewport)
      const r = flowLySpanToPanePixels(cx, cy, disk.radius * 2, viewport) / 2
      disks.push({
        key: `${overlay.id}-disk-${i}`,
        cx: px,
        cy: py,
        r,
      })
    }

    for (let i = 0; i < overlay.patches.length; i++) {
      const patch = overlay.patches[i]!
      const imageDataUrl = patchRasterDataUrl(overlay.fillColor, patch)
      // Fail closed: non-hex fillColor skips punch + raster (no invented color, no holes).
      if (imageDataUrl === '') continue
      const rect = patchPaneRect(patch, viewport)
      patchMaskRects.push({
        x: rect.left,
        y: rect.top,
        width: rect.width,
        height: rect.height,
      })
      patches.push({
        key: `${overlay.id}-patch-${i}`,
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
        imageDataUrl,
      })
    }

    if (disks.length === 0 && patches.length === 0) continue
    groups.push({
      key: overlay.id,
      fillColor: overlay.fillColor,
      fillOpacity: overlay.fillOpacity,
      disks,
      patches,
      patchMaskRects,
    })
  }

  return { groups }
}
