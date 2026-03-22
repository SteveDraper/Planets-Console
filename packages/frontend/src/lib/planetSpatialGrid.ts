/**
 * Uniform grid in planet (map cell) coordinates for sub-linear hover / radius queries.
 * Matches MapGraph: flow center (cx, cy) = (px + offset, -(py + offset)).
 */

export const PLANET_CELL_CENTER_OFFSET = 0.5

export type PlanetPoint = {
  id: string
  px: number
  py: number
}

export type PlanetSpatialGrid = {
  minX: number
  minY: number
  cellSize: number
  buckets: Map<string, PlanetPoint[]>
  /** All points (for safe fallback when the grid query would touch too many cells). */
  points: readonly PlanetPoint[]
}

type MapNodeLike = { id: string; x: number; y: number }

/**
 * Inverse of planet -> flow center: cx = px + offset, cy = -(py + offset).
 */
export function flowCenterToPlanet(flowX: number, flowY: number): { px: number; py: number } {
  return {
    px: flowX - PLANET_CELL_CENTER_OFFSET,
    py: -flowY - PLANET_CELL_CENTER_OFFSET,
  }
}

/** Minimum span (map units) used only for cell sizing when all planets coincide. */
const MIN_EXTENT_FOR_CELL_SIZING = 1

/** Do not visit more than this many grid cells in one query (avoids main-thread freeze). */
const MAX_GRID_CELL_VISITS = 12_000

/**
 * Cell side length from bbox and count: ~one planet per cell for uniform density.
 * Uses max(span) / sqrt(n) so collinear or very flat distributions never get microscopic cells
 * (sqrt(area/n) alone can be ~1e-9 and makes radius queries iterate billions of cells).
 */
function cellSizeFromBoundingBox(
  minX: number,
  maxX: number,
  minY: number,
  maxY: number,
  planetCount: number
): number {
  const spanX = Math.max(maxX - minX, 1e-9)
  const spanY = Math.max(maxY - minY, 1e-9)
  const area = spanX * spanY
  const n = Math.max(planetCount, 1)
  const extent = Math.max(spanX, spanY)
  const extentForSizing = Math.max(extent, MIN_EXTENT_FOR_CELL_SIZING)
  const fromArea = Math.sqrt(area / n)
  const fromExtent = extentForSizing / Math.sqrt(n)
  return Math.max(fromArea, fromExtent, 1e-6)
}

function bucketKey(ix: number, iy: number): string {
  return `${ix},${iy}`
}

export function buildPlanetSpatialGrid(nodes: MapNodeLike[]): PlanetSpatialGrid | null {
  if (nodes.length === 0) return null
  const points: PlanetPoint[] = []
  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  for (const n of nodes) {
    const px = Number(n.x)
    const py = Number(n.y)
    if (!Number.isFinite(px) || !Number.isFinite(py)) continue
    points.push({ id: n.id, px, py })
    minX = Math.min(minX, px)
    maxX = Math.max(maxX, px)
    minY = Math.min(minY, py)
    maxY = Math.max(maxY, py)
  }
  if (points.length === 0) return null
  const cellSize = cellSizeFromBoundingBox(minX, maxX, minY, maxY, points.length)
  const buckets = new Map<string, PlanetPoint[]>()
  for (const p of points) {
    const ix = Math.floor((p.px - minX) / cellSize)
    const iy = Math.floor((p.py - minY) / cellSize)
    const key = bucketKey(ix, iy)
    const list = buckets.get(key)
    if (list) list.push(p)
    else buckets.set(key, [p])
  }
  return { minX, minY, cellSize, buckets, points }
}

/**
 * Closest planet within Euclidean distance `radiusPlanet` in planet space, or null.
 * Flow distance equals planet distance (flip-Y is an isometry).
 */
function closestAmongPoints(
  candidates: readonly PlanetPoint[],
  planetX: number,
  planetY: number,
  r2: number
): string | null {
  let bestId: string | null = null
  let bestD2 = Infinity
  for (const p of candidates) {
    const dx = p.px - planetX
    const dy = p.py - planetY
    const d2 = dx * dx + dy * dy
    if (d2 < r2 && d2 < bestD2) {
      bestD2 = d2
      bestId = p.id
    }
  }
  return bestId
}

export function findClosestPlanetWithinRadius(
  grid: PlanetSpatialGrid,
  planetX: number,
  planetY: number,
  radiusPlanet: number
): string | null {
  const { minX, minY, cellSize, buckets, points } = grid
  const r = Math.max(radiusPlanet, 0)
  const r2 = r * r
  if (!Number.isFinite(planetX) || !Number.isFinite(planetY) || !Number.isFinite(r2)) return null
  if (!Number.isFinite(cellSize) || cellSize <= 0) {
    return closestAmongPoints(points, planetX, planetY, r2)
  }

  const ixMin = Math.floor((planetX - r - minX) / cellSize)
  const ixMax = Math.floor((planetX + r - minX) / cellSize)
  const iyMin = Math.floor((planetY - r - minY) / cellSize)
  const iyMax = Math.floor((planetY + r - minY) / cellSize)

  const nx = ixMax - ixMin + 1
  const ny = iyMax - iyMin + 1
  if (nx <= 0 || ny <= 0) return null
  if (nx * ny > MAX_GRID_CELL_VISITS) {
    return closestAmongPoints(points, planetX, planetY, r2)
  }

  let bestId: string | null = null
  let bestD2 = Infinity

  for (let ix = ixMin; ix <= ixMax; ix++) {
    for (let iy = iyMin; iy <= iyMax; iy++) {
      const list = buckets.get(bucketKey(ix, iy))
      if (!list) continue
      for (const p of list) {
        const dx = p.px - planetX
        const dy = p.py - planetY
        const d2 = dx * dx + dy * dy
        if (d2 < r2 && d2 < bestD2) {
          bestD2 = d2
          bestId = p.id
        }
      }
    }
  }
  return bestId
}
