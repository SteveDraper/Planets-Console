/**
 * Pane shapes for hybrid map region overlays.
 *
 * Coverage disks are SVG (opaque under one group opacity -- no alpha stacking,
 * cheap on pan/zoom). Nebula patches are small map-space PNGs cached by patch
 * identity and only reprojected each frame. Boundary overlays project to an
 * SVG path (line + arc edges) plus optional envelope disks.
 */

import type {
  MapRegionBoundaryArcEdge,
  MapRegionOverlay,
  MapRegionOverlayDisk,
  MapRegionOverlayPatch,
} from '../api/mapRegionOverlayTypes'
import {
  flowToPane,
  formatPaneCoordinate,
  gameMapCellCenterToFlow,
  mapLyToFlow,
  mapToPane,
  type CartographyOverlayViewport,
} from './cartography/cartographyOverlayGeometry'
import { flowLySpanToPanePixels } from './cartography/stellarCartographyOverlay'

export type MapRegionOverlayDiskShape = {
  key: string
  cx: number
  cy: number
  r: number
}

/** Stroke-only disk (e.g. homeworld 81/162 envelopes). */
export type MapRegionOverlayStrokeDiskShape = MapRegionOverlayDiskShape & {
  strokeColor: string
  strokeWidth: number
  strokeDasharray?: string
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
  /** Optional path stroke (defaults to fillColor when omitted). */
  strokeColor?: string
  strokeWidth?: number
  disks: MapRegionOverlayDiskShape[]
  /** Outline disks painted above the fill (not alpha-stacked fills). */
  strokeDisks: MapRegionOverlayStrokeDiskShape[]
  patches: MapRegionOverlayPatchShape[]
  /** Patch AABBs in pane px; punched from the disk-union mask. */
  patchMaskRects: { x: number; y: number; width: number; height: number }[]
  /** Closed SVG path for boundary geometry (map space projected to pane). */
  boundaryPath?: string
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
export function patchRasterDataUrl(fillColor: string, patch: MapRegionOverlayPatch): string {
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
  patch: MapRegionOverlayPatch,
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

function projectDiskShapes(
  disks: readonly MapRegionOverlayDisk[],
  overlayId: string,
  viewport: CartographyOverlayViewport
): MapRegionOverlayDiskShape[] {
  const shapes: MapRegionOverlayDiskShape[] = []
  for (let i = 0; i < disks.length; i++) {
    const disk = disks[i]!
    const { cx, cy } = gameMapCellCenterToFlow(disk.x, disk.y)
    const { px, py } = flowToPane(cx, cy, viewport)
    const r = flowLySpanToPanePixels(cx, cy, disk.radius * 2, viewport) / 2
    shapes.push({
      key: `${overlayId}-disk-${i}`,
      cx: px,
      cy: py,
      r,
    })
  }
  return shapes
}

/**
 * SVG arc in pane space.
 *
 * ``clockwise`` is the wire/map winding (Y-up). Endpoints are already projected
 * through ``mapToPane`` (Y-flip), so screen orientation matches that winding --
 * do not invert the sweep flag or short annular wedges become the long way
 * around (~360° - span) and fill almost the entire annulus.
 */
function paneArcCommand(
  start: { px: number; py: number },
  end: { px: number; py: number },
  center: { px: number; py: number },
  radius: number,
  clockwise: boolean
): string {
  const startAngle = Math.atan2(start.py - center.py, start.px - center.px)
  const endAngle = Math.atan2(end.py - center.py, end.px - center.px)
  let delta = endAngle - startAngle
  if (clockwise) {
    while (delta <= 0) delta += 2 * Math.PI
  } else {
    while (delta >= 0) delta -= 2 * Math.PI
  }
  const largeArc = Math.abs(delta) > Math.PI ? 1 : 0
  const sweep = clockwise ? 1 : 0
  return (
    `A ${formatPaneCoordinate(radius)} ${formatPaneCoordinate(radius)} 0 ${largeArc} ${sweep} ` +
    `${formatPaneCoordinate(end.px)} ${formatPaneCoordinate(end.py)}`
  )
}

function boundaryPathFromGeometry(
  vertices: readonly { x: number; y: number }[],
  edges: readonly { type: string; centerX?: number; centerY?: number; clockwise?: boolean }[],
  viewport: CartographyOverlayViewport
): string | null {
  if (vertices.length < 3 || edges.length !== vertices.length) return null
  const panePoints = vertices.map((v) => mapToPane(v.x, v.y, viewport))
  const first = panePoints[0]!
  let d = `M ${formatPaneCoordinate(first.px)} ${formatPaneCoordinate(first.py)}`
  for (let i = 0; i < edges.length; i++) {
    const edge = edges[i]!
    const start = panePoints[i]!
    const end = panePoints[(i + 1) % panePoints.length]!
    if (edge.type === 'line') {
      d += ` L ${formatPaneCoordinate(end.px)} ${formatPaneCoordinate(end.py)}`
      continue
    }
    if (edge.type !== 'arc') return null
    const arc = edge as MapRegionBoundaryArcEdge
    const paneCenter = mapToPane(arc.centerX, arc.centerY, viewport)
    const radius = Math.hypot(start.px - paneCenter.px, start.py - paneCenter.py)
    if (!(radius > 0)) return null
    d += paneArcCommand(start, end, paneCenter, radius, arc.clockwise)
  }
  return `${d} Z`
}

function buildCoverageGroup(
  overlay: MapRegionOverlay,
  viewport: CartographyOverlayViewport
): MapRegionOverlayPaneGroup | null {
  if (overlay.geometry.type !== 'coverage') return null
  const disks = projectDiskShapes(overlay.geometry.disks, overlay.id, viewport)
  const patches: MapRegionOverlayPatchShape[] = []
  const patchMaskRects: MapRegionOverlayPaneGroup['patchMaskRects'] = []

  for (let i = 0; i < overlay.geometry.patches.length; i++) {
    const patch = overlay.geometry.patches[i]!
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

  if (disks.length === 0 && patches.length === 0) return null
  return {
    key: overlay.id,
    fillColor: overlay.fillColor,
    fillOpacity: overlay.fillOpacity,
    disks,
    strokeDisks: [],
    patches,
    patchMaskRects,
  }
}

/** Homeworld cluster envelopes: distinct outline colors (81 vs 162 LY). */
const HOMEWORLD_ENVELOPE_STROKE_BY_RADIUS_LY: Record<number, string> = {
  81: '#38bdf8',
  162: '#c084fc',
}

const HOMEWORLD_SECTOR_KIND = 'homeworld-sector'
const HOMEWORLD_SECTOR_STROKE = '#fdba74'
const HOMEWORLD_ERROR_SECTOR_STROKE = '#fca5a5'
const HOMEWORLD_ENVELOPE_STROKE_WIDTH = 1.75

function homeworldEnvelopeStrokeColor(radiusLy: number): string {
  const rounded = Math.round(radiusLy)
  return HOMEWORLD_ENVELOPE_STROKE_BY_RADIUS_LY[rounded] ?? '#e2e8f0'
}

function buildBoundaryGroup(
  overlay: MapRegionOverlay,
  viewport: CartographyOverlayViewport
): MapRegionOverlayPaneGroup | null {
  if (overlay.geometry.type !== 'boundary') return null
  const boundaryPath = boundaryPathFromGeometry(
    overlay.geometry.vertices,
    overlay.geometry.edges,
    viewport
  )
  const rawDisks = overlay.geometry.disks ?? []
  const isHomeworldSector = overlay.kind === HOMEWORLD_SECTOR_KIND
  // Homeworld envelopes are stroke outlines with per-radius colors; other
  // boundary disks keep the legacy filled-disk path.
  const disks = isHomeworldSector
    ? []
    : projectDiskShapes(rawDisks, overlay.id, viewport)
  const strokeDisks: MapRegionOverlayStrokeDiskShape[] = isHomeworldSector
    ? projectDiskShapes(rawDisks, overlay.id, viewport).map((disk, i) => ({
        ...disk,
        strokeColor: homeworldEnvelopeStrokeColor(rawDisks[i]!.radius),
        strokeWidth: HOMEWORLD_ENVELOPE_STROKE_WIDTH,
      }))
    : []
  if (boundaryPath == null && disks.length === 0 && strokeDisks.length === 0) return null
  const strokeColor = isHomeworldSector
    ? overlay.status === 'error'
      ? HOMEWORLD_ERROR_SECTOR_STROKE
      : HOMEWORLD_SECTOR_STROKE
    : undefined
  return {
    key: overlay.id,
    // Homeworld sectors are outline-only; wire fill fields stay for shared shape.
    fillColor: overlay.fillColor,
    fillOpacity: isHomeworldSector ? 0 : overlay.fillOpacity,
    strokeColor,
    strokeWidth: isHomeworldSector ? 1.5 : undefined,
    disks,
    strokeDisks,
    patches: [],
    patchMaskRects: [],
    boundaryPath: boundaryPath ?? undefined,
  }
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
    const group =
      overlay.geometry.type === 'coverage'
        ? buildCoverageGroup(overlay, viewport)
        : buildBoundaryGroup(overlay, viewport)
    if (group != null) groups.push(group)
  }

  return { groups }
}
