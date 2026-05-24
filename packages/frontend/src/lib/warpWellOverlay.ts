import type { MapNode } from '../api/bff'
import {
  flowBoundingBoxFromWellCells,
  flowBoundsIntersect,
  normalWellGridSegmentsFromCells,
  type WarpWellGridSegmentFlow,
} from './warpWell'

/** Show normal warp well outlines when zoom >= this (pixels per flow unit). */
export const WARP_WELL_OVERLAY_ZOOM_THRESHOLD = 5

export type WarpWellOverlayViewport = {
  width: number
  height: number
  tx: number
  ty: number
  scale: number
}

export type WarpWellOverlayPaneLine = {
  key: string
  x1: number
  y1: number
  x2: number
  y2: number
}

function clipWarpWellSegmentToFlowViewport(
  s: WarpWellGridSegmentFlow,
  fxMin: number,
  fxMax: number,
  fyMin: number,
  fyMax: number
): WarpWellGridSegmentFlow | null {
  const { x1, y1, x2, y2 } = s
  if (x1 === x2) {
    const x = x1
    if (x < fxMin || x > fxMax) return null
    const yLo = Math.min(y1, y2)
    const yHi = Math.max(y1, y2)
    const cl = Math.max(yLo, fyMin)
    const ch = Math.min(yHi, fyMax)
    if (ch < cl) return null
    return { x1: x, y1: cl, x2: x, y2: ch }
  }
  if (y1 === y2) {
    const y = y1
    if (y < fyMin || y > fyMax) return null
    const xLo = Math.min(x1, x2)
    const xHi = Math.max(x1, x2)
    const cl = Math.max(xLo, fxMin)
    const ch = Math.min(xHi, fxMax)
    if (ch < cl) return null
    return { x1: cl, y1: y, x2: ch, y2: y }
  }
  return null
}

/** Build pane-pixel SVG line segments for the normal warp well overlay at the given zoom. */
export function buildWarpWellOverlayPaneLines(
  mapNodes: readonly MapNode[],
  viewport: WarpWellOverlayViewport,
  minScale: number
): WarpWellOverlayPaneLine[] {
  const { width, height, tx, ty, scale } = viewport
  if (width <= 0 || height <= 0 || !Number.isFinite(scale) || scale < minScale) {
    return []
  }

  const flowXMin = -tx / scale
  const flowXMax = (width - tx) / scale
  const flowYMin = -ty / scale
  const flowYMax = (height - ty) / scale

  const lines: WarpWellOverlayPaneLine[] = []
  for (const n of mapNodes) {
    const cells = n.normalWellCells
    if (cells == null || cells.length === 0) continue
    const wellBounds = flowBoundingBoxFromWellCells(cells)
    if (
      wellBounds == null ||
      !flowBoundsIntersect(wellBounds, flowXMin, flowXMax, flowYMin, flowYMax)
    ) {
      continue
    }
    const segs = normalWellGridSegmentsFromCells(cells)
    segs.forEach((s, i) => {
      const clipped = clipWarpWellSegmentToFlowViewport(s, flowXMin, flowXMax, flowYMin, flowYMax)
      if (clipped == null) return
      const x1 = clipped.x1 * scale + tx
      const y1 = clipped.y1 * scale + ty
      const x2 = clipped.x2 * scale + tx
      const y2 = clipped.y2 * scale + ty
      if (![x1, y1, x2, y2].every((v) => Number.isFinite(v))) return
      lines.push({ key: `${n.id}-${i}`, x1, y1, x2, y2 })
    })
  }
  return lines
}
