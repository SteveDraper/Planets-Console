import {
  boundaryPathsFromMapPolygons,
  type CartographyOverlayViewport,
  type MapBounds,
  type MapPoint,
} from './cartographyOverlayGeometry'
import { stitchMapSegmentsToPolylines } from './nebulaCloudOverlay'
import { starClusterRadiationSumAt, type StarClusterRadiationBody } from './starClusterRadiation'

/** Side length of a map ly cell (integer cell ``cx`` spans ``[cx, cx + 1]``). */
export const MAP_CELL_SIZE_LY = 1

type MapSegment = [MapPoint, MapPoint]

function cellKey(cellX: number, cellY: number): string {
  return `${cellX},${cellY}`
}

function integerCellSpan(bounds: MapBounds): {
  minCellX: number
  maxCellX: number
  minCellY: number
  maxCellY: number
} {
  return {
    minCellX: Math.floor(bounds.minX),
    maxCellX: Math.ceil(bounds.maxX) - 1,
    minCellY: Math.floor(bounds.minY),
    maxCellY: Math.ceil(bounds.maxY) - 1,
  }
}

function collectActiveMapCells(
  bodies: readonly StarClusterRadiationBody[],
  bounds: MapBounds
): Set<string> {
  const active = new Set<string>()
  const { minCellX, maxCellX, minCellY, maxCellY } = integerCellSpan(bounds)
  for (let cellY = minCellY; cellY <= maxCellY; cellY += 1) {
    for (let cellX = minCellX; cellX <= maxCellX; cellX += 1) {
      if (starClusterRadiationSumAt(cellX, cellY, bodies) > 0) {
        active.add(cellKey(cellX, cellY))
      }
    }
  }
  return active
}

function isActive(active: Set<string>, cellX: number, cellY: number): boolean {
  return active.has(cellKey(cellX, cellY))
}

function addEdge(segments: MapSegment[], start: MapPoint, end: MapPoint): void {
  segments.push([start, end])
}

/** Boundary edges of the union of 1 ly cells whose sample index has host flux > 0. */
export function mapCellUnionBoundarySegments(
  bodies: readonly StarClusterRadiationBody[],
  bounds: MapBounds
): MapSegment[] {
  const active = collectActiveMapCells(bodies, bounds)
  const segments: MapSegment[] = []

  for (const key of active) {
    const [cellXText, cellYText] = key.split(',')
    const cellX = Number(cellXText)
    const cellY = Number(cellYText)
    if (!Number.isFinite(cellX) || !Number.isFinite(cellY)) continue

    if (!isActive(active, cellX, cellY + 1)) {
      addEdge(segments, { x: cellX, y: cellY + 1 }, { x: cellX + 1, y: cellY + 1 })
    }
    if (!isActive(active, cellX + 1, cellY)) {
      addEdge(segments, { x: cellX + 1, y: cellY + 1 }, { x: cellX + 1, y: cellY })
    }
    if (!isActive(active, cellX, cellY - 1)) {
      addEdge(segments, { x: cellX + 1, y: cellY }, { x: cellX, y: cellY })
    }
    if (!isActive(active, cellX - 1, cellY)) {
      addEdge(segments, { x: cellX, y: cellY }, { x: cellX, y: cellY + 1 })
    }
  }

  return segments
}

export function mapCellUnionBoundaryPolylines(
  bodies: readonly StarClusterRadiationBody[],
  bounds: MapBounds
): MapPoint[][] {
  const segments = mapCellUnionBoundarySegments(bodies, bounds)
  if (segments.length === 0) return []
  return stitchMapSegmentsToPolylines(segments, 1e-6)
}

export function mapCellUnionBoundaryPaths(
  bodies: readonly StarClusterRadiationBody[],
  bounds: MapBounds,
  viewport: CartographyOverlayViewport
): string[] {
  return boundaryPathsFromMapPolygons(mapCellUnionBoundaryPolylines(bodies, bounds), viewport)
}
