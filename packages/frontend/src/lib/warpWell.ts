/**
 * Render server-provided normal warp well cells on the map (no well geometry math).
 */

export type WarpWellMapCell = {
  x: number
  y: number
}

/** Axis-aligned bounds in React Flow space for culling. */
export type NormalWarpWellFlowBounds = {
  flowXMin: number
  flowXMax: number
  flowYMin: number
  flowYMax: number
}

/** Axis-aligned segment in React Flow coordinates (same space as the coordinate grid). */
export type WarpWellGridSegmentFlow = {
  x1: number
  y1: number
  x2: number
  y2: number
}

function normalizeWellCells(cells: WarpWellMapCell[] | undefined): WarpWellMapCell[] {
  if (!Array.isArray(cells)) return []
  const out: WarpWellMapCell[] = []
  for (const c of cells) {
    const x = typeof c.x === 'number' ? c.x : Number(c.x)
    const y = typeof c.y === 'number' ? c.y : Number(c.y)
    if (Number.isFinite(x) && Number.isFinite(y)) {
      out.push({ x, y })
    }
  }
  return out
}

/**
 * Tight axis-aligned box in flow coordinates that contains every normal-well grid segment.
 * Map cells use gx/gy; cell edges match `CoordinateGridOverlay` (x from gx to gx+1, y from -(gy+1) to -gy).
 */
export function flowBoundingBoxFromWellCells(
  cells: WarpWellMapCell[] | undefined
): NormalWarpWellFlowBounds | null {
  const normalized = normalizeWellCells(cells)
  if (normalized.length === 0) return null
  let flowXMin = Infinity
  let flowXMax = -Infinity
  let flowYMin = Infinity
  let flowYMax = -Infinity
  for (const { x: gx, y: gy } of normalized) {
    flowXMin = Math.min(flowXMin, gx)
    flowXMax = Math.max(flowXMax, gx + 1)
    const yTop = -(gy + 1)
    const yBottom = -gy
    flowYMin = Math.min(flowYMin, yTop)
    flowYMax = Math.max(flowYMax, yBottom)
  }
  if (![flowXMin, flowXMax, flowYMin, flowYMax].every(Number.isFinite)) return null
  return { flowXMin, flowXMax, flowYMin, flowYMax }
}

/** Whether two closed flow-axis rectangles overlap (same convention as segment clipping). */
export function flowBoundsIntersect(
  a: NormalWarpWellFlowBounds,
  flowXMin: number,
  flowXMax: number,
  flowYMin: number,
  flowYMax: number
): boolean {
  return (
    a.flowXMin <= flowXMax &&
    a.flowXMax >= flowXMin &&
    a.flowYMin <= flowYMax &&
    a.flowYMax >= flowYMin
  )
}

function warpWellGridSegmentKey(s: WarpWellGridSegmentFlow): string {
  const { x1, y1, x2, y2 } = s
  if (x1 === x2) {
    const yLo = Math.min(y1, y2)
    const yHi = Math.max(y1, y2)
    return `v|${x1}|${yLo}|${yHi}`
  }
  const xLo = Math.min(x1, x2)
  const xHi = Math.max(x1, x2)
  return `h|${y1}|${xLo}|${xHi}`
}

function keyToSegment(key: string): WarpWellGridSegmentFlow | null {
  const p = key.split('|')
  if (p[0] === 'v' && p.length === 4) {
    const x = Number(p[1])
    const yLo = Number(p[2])
    const yHi = Number(p[3])
    if (![x, yLo, yHi].every(Number.isFinite)) return null
    return { x1: x, y1: yLo, x2: x, y2: yHi }
  }
  if (p[0] === 'h' && p.length === 4) {
    const y = Number(p[1])
    const xLo = Number(p[2])
    const xHi = Number(p[3])
    if (![y, xLo, xHi].every(Number.isFinite)) return null
    return { x1: xLo, y1: y, x2: xHi, y2: y }
  }
  return null
}

/**
 * Every coordinate edge of each map cell in the normal warp well (same integer lines as
 * `CoordinateGridOverlay`), with shared edges between adjacent well cells deduplicated.
 */
export function normalWellGridSegmentsFromCells(
  cells: WarpWellMapCell[] | undefined
): WarpWellGridSegmentFlow[] {
  const normalized = normalizeWellCells(cells)
  if (normalized.length === 0) return []
  const keySet = new Set<string>()

  for (const { x: gx, y: gy } of normalized) {
    const yTop = -(gy + 1)
    const yBottom = -gy
    const edges: WarpWellGridSegmentFlow[] = [
      { x1: gx, y1: yTop, x2: gx, y2: yBottom },
      { x1: gx + 1, y1: yTop, x2: gx + 1, y2: yBottom },
      { x1: gx, y1: yTop, x2: gx + 1, y2: yTop },
      { x1: gx, y1: yBottom, x2: gx + 1, y2: yBottom },
    ]
    for (const e of edges) {
      keySet.add(warpWellGridSegmentKey(e))
    }
  }

  const out: WarpWellGridSegmentFlow[] = []
  for (const k of keySet) {
    const seg = keyToSegment(k)
    if (seg != null) out.push(seg)
  }
  return out
}
