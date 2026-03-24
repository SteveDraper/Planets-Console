/**
 * Warp wells in map coordinates. Distance is Cartesian (Euclidean) in the map plane.
 */

export type WarpWellType = 'normal' | 'hyperjump'

const NORMAL_RADIUS = 3
const HYPERJUMP_EXCLUSIVE_RADIUS = 3

/**
 * Reads planets.nu-style `debrisdisk`; non-zero means the planet sits in a debris disk
 * and has no warp wells.
 */
export function planetIsInDebrisDisk(planet: Record<string, unknown> | undefined): boolean {
  if (planet == null) return false
  const raw = planet.debrisdisk ?? planet.debrisDisk
  const n = typeof raw === 'number' ? raw : Number(raw)
  return Number.isFinite(n) && n !== 0
}

export function warpWellCartesianDistance(
  ax: number,
  ay: number,
  bx: number,
  by: number
): number {
  return Math.hypot(ax - bx, ay - by)
}

/**
 * Whether `(queryX, queryY)` lies in the given warp well around the planet at `(planetX, planetY)`.
 * Debris-disk planets never have a well.
 */
export function isCoordinateInWarpWell(
  planetX: number,
  planetY: number,
  planet: Record<string, unknown> | undefined,
  queryX: number,
  queryY: number,
  wellType: WarpWellType
): boolean {
  if (planetIsInDebrisDisk(planet)) return false
  const d = warpWellCartesianDistance(planetX, planetY, queryX, queryY)
  if (wellType === 'normal') {
    return d <= NORMAL_RADIUS
  }
  return d < HYPERJUMP_EXCLUSIVE_RADIUS
}

/**
 * Map cells whose center lies in the given warp well. When ``planet`` is set and the planet is
 * in a debris disk, returns no cells (matches ``api.concepts.warp_well``).
 */
export function mapCellsInWarpWell(
  planetMapX: number,
  planetMapY: number,
  wellType: WarpWellType,
  planet?: Record<string, unknown>
): { gx: number; gy: number }[] {
  if (!Number.isFinite(planetMapX) || !Number.isFinite(planetMapY)) return []
  if (planetIsInDebrisDisk(planet)) return []
  const px = planetMapX
  const py = planetMapY
  const out: { gx: number; gy: number }[] = []
  for (let dgx = -NORMAL_RADIUS; dgx <= NORMAL_RADIUS; dgx++) {
    for (let dgy = -NORMAL_RADIUS; dgy <= NORMAL_RADIUS; dgy++) {
      const gx = px + dgx
      const gy = py + dgy
      const d = warpWellCartesianDistance(px, py, gx, gy)
      if (wellType === 'normal') {
        if (d <= NORMAL_RADIUS) out.push({ gx, gy })
      } else if (d < HYPERJUMP_EXCLUSIVE_RADIUS) {
        out.push({ gx, gy })
      }
    }
  }
  return out
}

/**
 * Map cells whose center lies in the normal warp well (Euclidean distance from planet map cell
 * index `(planetMapX, planetMapY)` to `(gx, gy)` at most `NORMAL_RADIUS`). Same as distance
 * between cell centers because the offset is identical on both axes.
 *
 * Does not take planet snapshot: debris filtering is done by callers (e.g. map overlay).
 */
export function mapCellsWithCenterInNormalWarpWell(
  planetMapX: number,
  planetMapY: number
): { gx: number; gy: number }[] {
  return mapCellsInWarpWell(planetMapX, planetMapY, 'normal', undefined)
}

/** Axis-aligned bounds in React Flow space for culling (see `normalWarpWellFlowBoundingBox`). */
export type NormalWarpWellFlowBounds = {
  flowXMin: number
  flowXMax: number
  flowYMin: number
  flowYMax: number
}

/**
 * Tight axis-aligned box in flow coordinates that contains every normal-well grid segment.
 * Map cells in the well have gx in [px - R, px + R] and gy in [py - R, py + R]; cell edges match
 * `CoordinateGridOverlay` (x from gx to gx+1, y from -(gy+1) to -gy).
 */
export function normalWarpWellFlowBoundingBox(
  planetMapX: number,
  planetMapY: number
): NormalWarpWellFlowBounds | null {
  if (!Number.isFinite(planetMapX) || !Number.isFinite(planetMapY)) return null
  const px = planetMapX
  const py = planetMapY
  const r = NORMAL_RADIUS
  return {
    flowXMin: px - r,
    flowXMax: px + r + 1,
    flowYMin: -(py + r + 1),
    flowYMax: -(py - r),
  }
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

/** Axis-aligned segment in React Flow coordinates (same space as the coordinate grid). */
export type WarpWellGridSegmentFlow = {
  x1: number
  y1: number
  x2: number
  y2: number
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
export function normalWarpWellGridSegmentsFlow(
  planetMapX: number,
  planetMapY: number
): WarpWellGridSegmentFlow[] {
  if (!Number.isFinite(planetMapX) || !Number.isFinite(planetMapY)) return []
  const keySet = new Set<string>()

  for (const { gx, gy } of mapCellsWithCenterInNormalWarpWell(planetMapX, planetMapY)) {
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
