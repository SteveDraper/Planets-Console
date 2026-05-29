import type { NebulaOverlayCircle } from '../api/bff'
import {
  boundaryPathFromMapPolygons,
  boundsIntersectsViewport,
  formatPaneCoordinate,
  isPointInsideMapPolygon,
  mapBoundsFromCircles,
  mapToPane,
  maxSearchRadiusFromCircles,
  paneRectFromBounds,
  type CartographyOverlayViewport,
  type MapPoint,
} from './cartographyOverlayGeometry'
import {
  boundaryPolygonFromOrigin,
  DEFAULT_ISO_CONTOUR_RAY_COUNT,
} from './isoContourRayMarch'
import { PLANET_CELL_CENTER_OFFSET } from '../planetSpatialGrid'
import {
  buildScalarGrid,
  gridPointToMap,
  type DensityGrid,
} from './scalarFieldGrid'
import { rasterizeMapField } from './rasterizeMapField'
import {
  NEBULA_BOUNDARY_DENSITY_THRESHOLD,
  NEBULA_CLOUD_COLOR_RGB,
  NEBULA_CLOUD_NOISE_STRENGTH,
  NEBULA_STROKE_COLOR,
  NEBULA_STROKE_WIDTH,
  nebulaFillOpacityFromHostDensity,
  nebulaVisibilityLyFromDensity,
} from './stellarCartographyTheme'

export type NebulaCloudViewport = CartographyOverlayViewport
export type { DensityGrid } from './scalarFieldGrid'
export { isPointInsideMapPolygon }

export type NebulaCloudCenter = {
  x: number
  y: number
  radius: number
  intensity: number
}

export type NebulaCloudPaneShape = {
  key: string
  left: number
  top: number
  width: number
  height: number
  imageDataUrl: string
  boundaryPath: string
  fillClipPathId: string
  stroke: string
  strokeWidth: number
}

/** Cap map-space raster size; larger nebulae use a coarser ly/sample step. */
export const NEBULA_MAX_RASTER_PX = 512
export const NEBULA_BOUNDARY_MAX_GRID_CELLS = 512

type MapSegment = [MapPoint, MapPoint]

type NebulaCloudRasterCache = {
  signature: string
  bounds: { minX: number; minY: number; maxX: number; maxY: number }
  imageDataUrl: string
}

const rasterCache = new Map<string, NebulaCloudRasterCache>()

export function clearNebulaCloudRasterCache(): void {
  rasterCache.clear()
}

/** Integer map cell for Core sample_at / host density (matches hover sampling). */
export function mapLyToSampleCell(mapX: number, mapY: number): { cellX: number; cellY: number } {
  return {
    cellX: Math.round(mapX - PLANET_CELL_CENTER_OFFSET),
    cellY: Math.round(mapY - PLANET_CELL_CENTER_OFFSET),
  }
}

/** Continuous falloff sum for boundary iso-contours. */
export function nebulaDensityAt(
  centers: readonly NebulaCloudCenter[],
  mapX: number,
  mapY: number
): number {
  let total = 0
  for (const center of centers) {
    if (center.radius <= 0) continue
    const dist = Math.hypot(mapX - center.x, mapY - center.y)
    if (dist <= center.radius) {
      total += center.intensity * (1 - dist / center.radius)
    }
  }
  return total
}

/** Host density: CEIL per center, matches tooltip sampling in Core sample_at. */
export function nebulaHostDensityAt(
  centers: readonly NebulaCloudCenter[],
  mapX: number,
  mapY: number
): number {
  let total = 0
  for (const center of centers) {
    if (center.radius <= 0) continue
    const dist = Math.hypot(mapX - center.x, mapY - center.y)
    if (dist <= center.radius) {
      total += Math.ceil(center.intensity * (1 - dist / center.radius))
    }
  }
  return total
}

/** Visibility in ly from host density (same formula as hover tooltips). */
export function nebulaVisibilityAt(density: number): number {
  return nebulaVisibilityLyFromDensity(density)
}

function cloudNoise(mapX: number, mapY: number): number {
  const value = Math.sin(mapX * 12.9898 + mapY * 78.233) * 43758.5453
  return value - Math.floor(value)
}

/** Fill opacity from host density with light cloud noise for texture. */
export function nebulaCloudOpacityAt(hostDensity: number, mapX: number, mapY: number): number {
  if (hostDensity <= 0) return 0
  const base = nebulaFillOpacityFromHostDensity(hostDensity)
  const noise =
    1 - NEBULA_CLOUD_NOISE_STRENGTH + NEBULA_CLOUD_NOISE_STRENGTH * cloudNoise(mapX, mapY)
  return base * noise
}

/** Map fill opacity from host density; zero outside nebula coverage. */
export function nebulaCloudFillOpacityAt(
  hostDensity: number,
  mapX: number,
  mapY: number
): number {
  if (hostDensity <= 0) return 0
  return nebulaCloudOpacityAt(hostDensity, mapX, mapY)
}

export function groupNebulaCentersByName(
  circles: readonly NebulaOverlayCircle[]
): Map<string, NebulaCloudCenter[]> {
  const grouped = new Map<string, NebulaCloudCenter[]>()
  for (const circle of circles) {
    const name = circle.name?.trim() || `neb-${circle.id}`
    const centers = grouped.get(name) ?? []
    centers.push({
      x: circle.x,
      y: circle.y,
      radius: circle.radius,
      intensity: circle.intensity ?? 1,
    })
    grouped.set(name, centers)
  }
  return grouped
}

/** Ray count for the analytic density iso-contour (map space). */
export const NEBULA_BOUNDARY_RAY_COUNT = DEFAULT_ISO_CONTOUR_RAY_COUNT

const BOUNDARY_POSITION_EPSILON = 1e-4

function activeNebulaCenters(
  centers: readonly NebulaCloudCenter[],
  threshold: number = NEBULA_BOUNDARY_DENSITY_THRESHOLD
): NebulaCloudCenter[] {
  return centers.filter((center) => center.radius > 0 && center.intensity > threshold)
}

/** Solo iso-radius: density from this center alone equals the threshold. */
export function soloNebulaBoundaryRadius(
  center: NebulaCloudCenter,
  threshold: number = NEBULA_BOUNDARY_DENSITY_THRESHOLD
): number | null {
  if (center.radius <= 0 || center.intensity <= threshold) return null
  return center.radius * (1 - threshold / center.intensity)
}

function nebulaInteriorOrigin(
  centers: readonly NebulaCloudCenter[],
  threshold: number
): MapPoint | null {
  let best = { x: 0, y: 0, density: Number.NEGATIVE_INFINITY }
  for (const center of centers) {
    const density = nebulaDensityAt(centers, center.x, center.y)
    if (density > best.density) {
      best = { x: center.x, y: center.y, density }
    }
  }
  if (best.density >= threshold) {
    return { x: best.x, y: best.y }
  }

  let weight = 0
  let x = 0
  let y = 0
  for (const center of centers) {
    x += center.x * center.intensity
    y += center.y * center.intensity
    weight += center.intensity
  }
  if (weight <= 0) return null
  return { x: x / weight, y: y / weight }
}

/** Closed iso-contour of summed nebula density in map coordinates. */
export function nebulaBoundaryPolygonFromCenters(
  centers: readonly NebulaCloudCenter[],
  threshold: number = NEBULA_BOUNDARY_DENSITY_THRESHOLD,
  rayCount: number = NEBULA_BOUNDARY_RAY_COUNT
): MapPoint[] {
  const active = activeNebulaCenters(centers, threshold)
  if (active.length === 0) return []

  const origin = nebulaInteriorOrigin(active, threshold)
  if (origin == null) return []

  const globalMaxRadius = maxSearchRadiusFromCircles(origin, active)
  const fieldAt = (mapX: number, mapY: number): number => nebulaDensityAt(active, mapX, mapY)
  return boundaryPolygonFromOrigin(
    origin,
    fieldAt,
    threshold,
    globalMaxRadius,
    globalMaxRadius,
    rayCount
  )
}

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

function singleCircleBoundaryPath(
  center: NebulaCloudCenter,
  mapRadius: number,
  viewport: NebulaCloudViewport
): string {
  const paneCenter = mapToPane(center.x, center.y, viewport)
  const paneEast = mapToPane(center.x + mapRadius, center.y, viewport)
  const paneRadius = Math.max(BOUNDARY_POSITION_EPSILON, Math.abs(paneEast.px - paneCenter.px))
  const east = {
    px: paneCenter.px + paneRadius,
    py: paneCenter.py,
  }
  const west = {
    px: paneCenter.px - paneRadius,
    py: paneCenter.py,
  }
  return (
    `M ${formatPaneCoordinate(east.px)} ${formatPaneCoordinate(east.py)}` +
    paneArcCommand(east, west, paneCenter, paneRadius, true) +
    paneArcCommand(west, east, paneCenter, paneRadius, true) +
    ' Z'
  )
}

export function nebulaBoundaryPathFromCenters(
  centers: readonly NebulaCloudCenter[],
  viewport: NebulaCloudViewport,
  threshold: number = NEBULA_BOUNDARY_DENSITY_THRESHOLD
): string {
  const active = activeNebulaCenters(centers, threshold)
  if (active.length === 0) return ''

  if (active.length === 1) {
    const soloRadius = soloNebulaBoundaryRadius(active[0]!, threshold)
    if (soloRadius != null && soloRadius > 0) {
      return singleCircleBoundaryPath(active[0]!, soloRadius, viewport)
    }
  }

  const polygon = nebulaBoundaryPolygonFromCenters(active, threshold)
  if (polygon.length < 3) return ''
  const path = nebulaBoundaryPathFromPolylines([polygon], viewport)
  if (path.length > 0 && !path.endsWith(' Z')) {
    return `${path} Z`
  }
  return path
}

export function nebulaBoundaryPolylinesFromCenters(
  centers: readonly NebulaCloudCenter[],
  threshold: number = NEBULA_BOUNDARY_DENSITY_THRESHOLD
): MapPoint[][] {
  const polygon = nebulaBoundaryPolygonFromCenters(centers, threshold)
  if (polygon.length < 2) return []
  return [polygon]
}

export function nebulaBoundaryPathFromPolylines(
  polylines: readonly (readonly MapPoint[])[],
  viewport: NebulaCloudViewport
): string {
  return boundaryPathFromMapPolygons(polylines, viewport)
}

export function buildDensityGrid(
  centers: readonly NebulaCloudCenter[],
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
  step: number
): DensityGrid {
  return buildScalarGrid(bounds, step, (mapX, mapY) => nebulaDensityAt(centers, mapX, mapY))
}

function mapPointKey(p: MapPoint): string {
  return `${p.x.toFixed(6)},${p.y.toFixed(6)}`
}

function gridEdgeKey(colA: number, rowA: number, colB: number, rowB: number): string {
  if (colA < colB || (colA === colB && rowA < rowB)) {
    return `${colA},${rowA}|${colB},${rowB}`
  }
  return `${colB},${rowB}|${colA},${rowA}`
}

function cachedGridEdgeCrossing(
  cache: Map<string, MapPoint>,
  grid: DensityGrid,
  colA: number,
  rowA: number,
  valueA: number,
  colB: number,
  rowB: number,
  valueB: number,
  threshold: number
): MapPoint | null {
  const key = gridEdgeKey(colA, rowA, colB, rowB)
  if (cache.has(key)) {
    return cache.get(key) ?? null
  }

  const point = edgeThresholdCrossing(
    gridPointToMap(grid, colA, rowA),
    valueA,
    gridPointToMap(grid, colB, rowB),
    valueB,
    threshold
  )
  if (point != null) {
    cache.set(key, point)
  }
  return point
}

function edgeThresholdCrossing(
  a: MapPoint,
  valueA: number,
  b: MapPoint,
  valueB: number,
  threshold: number
): MapPoint | null {
  const aInside = valueA >= threshold
  const bInside = valueB >= threshold
  if (aInside === bInside) return null
  const delta = valueB - valueA
  const t = Math.abs(delta) < 1e-9 ? 0.5 : (threshold - valueA) / delta
  return {
    x: a.x + t * (b.x - a.x),
    y: a.y + t * (b.y - a.y),
  }
}

function addSegment(segments: MapSegment[], start: MapPoint | null, end: MapPoint | null): void {
  if (start == null || end == null) return
  segments.push([start, end])
}

/** Marching squares contour in map coordinates (cached; cheap to project each frame). */
export function nebulaBoundarySegmentsFromGrid(
  grid: DensityGrid,
  centers: readonly NebulaCloudCenter[],
  threshold: number = NEBULA_BOUNDARY_DENSITY_THRESHOLD
): MapSegment[] {
  const segments: MapSegment[] = []
  const crossingCache = new Map<string, MapPoint>()

  const valueAt = (col: number, row: number): number => {
    if (col >= 0 && row >= 0 && col < grid.cols && row < grid.rows) {
      return grid.values[row * grid.cols + col] ?? 0
    }
    const point = gridPointToMap(grid, col, row)
    return nebulaDensityAt(centers, point.x, point.y)
  }

  for (let row = 0; row < grid.rows - 1; row += 1) {
    for (let col = 0; col < grid.cols - 1; col += 1) {
      const v0 = valueAt(col, row)
      const v1 = valueAt(col + 1, row)
      const v2 = valueAt(col + 1, row + 1)
      const v3 = valueAt(col, row + 1)

      const top = cachedGridEdgeCrossing(
        crossingCache,
        grid,
        col,
        row,
        v0,
        col + 1,
        row,
        v1,
        threshold
      )
      const right = cachedGridEdgeCrossing(
        crossingCache,
        grid,
        col + 1,
        row,
        v1,
        col + 1,
        row + 1,
        v2,
        threshold
      )
      const bottom = cachedGridEdgeCrossing(
        crossingCache,
        grid,
        col,
        row + 1,
        v3,
        col + 1,
        row + 1,
        v2,
        threshold
      )
      const left = cachedGridEdgeCrossing(
        crossingCache,
        grid,
        col,
        row,
        v0,
        col,
        row + 1,
        v3,
        threshold
      )

      const i0 = v0 >= threshold ? 1 : 0
      const i1 = v1 >= threshold ? 1 : 0
      const i2 = v2 >= threshold ? 1 : 0
      const i3 = v3 >= threshold ? 1 : 0
      const caseIndex = i0 | (i1 << 1) | (i2 << 2) | (i3 << 3)
      if (caseIndex === 0 || caseIndex === 15) continue

      if (caseIndex === 5 || caseIndex === 10) {
        const centerAverage = (v0 + v1 + v2 + v3) / 4
        const connectPrimary =
          caseIndex === 5 ? centerAverage >= threshold : centerAverage < threshold
        if (connectPrimary) {
          addSegment(segments, top, right)
          addSegment(segments, left, bottom)
        } else {
          addSegment(segments, top, left)
          addSegment(segments, bottom, right)
        }
        continue
      }

      switch (caseIndex) {
        case 1:
          addSegment(segments, left, bottom)
          break
        case 2:
          addSegment(segments, bottom, right)
          break
        case 3:
          addSegment(segments, left, right)
          break
        case 4:
          addSegment(segments, top, right)
          break
        case 6:
          addSegment(segments, top, bottom)
          break
        case 7:
          addSegment(segments, left, top)
          break
        case 8:
          addSegment(segments, left, top)
          break
        case 9:
          addSegment(segments, top, bottom)
          break
        case 11:
          addSegment(segments, top, right)
          break
        case 12:
          addSegment(segments, left, right)
          break
        case 13:
          addSegment(segments, bottom, right)
          break
        case 14:
          addSegment(segments, left, bottom)
          break
        default:
          break
      }
    }
  }

  return segments
}

export function mergeNearbyMapPoints(
  segments: readonly MapSegment[],
  tolerance: number
): MapSegment[] {
  if (tolerance <= 0) return [...segments]

  const canonicalPoints: MapPoint[] = []
  const resolvePoint = (point: MapPoint): MapPoint => {
    for (const existing of canonicalPoints) {
      if (Math.hypot(existing.x - point.x, existing.y - point.y) <= tolerance) {
        return existing
      }
    }
    canonicalPoints.push(point)
    return point
  }

  return segments.map(([start, end]) => [resolvePoint(start), resolvePoint(end)])
}

/** Walk shared contour edges into continuous open or closed polylines. */
export function stitchMapSegmentsToPolylines(
  segments: readonly MapSegment[],
  mergeTolerance = 0
): MapPoint[][] {
  const mergedSegments = mergeNearbyMapPoints(segments, mergeTolerance)
  if (mergedSegments.length === 0) return []

  const canonicalByKey = new Map<string, MapPoint>()
  const canonicalPoint = (point: MapPoint): MapPoint => {
    const key = mapPointKey(point)
    const existing = canonicalByKey.get(key)
    if (existing != null) return existing
    canonicalByKey.set(key, point)
    return point
  }

  type TrackedSegment = { start: MapPoint; end: MapPoint; used: boolean }
  const tracked: TrackedSegment[] = mergedSegments.map(([start, end]) => ({
    start: canonicalPoint(start),
    end: canonicalPoint(end),
    used: false,
  }))

  const edgesAtVertex = new Map<string, number[]>()
  for (let index = 0; index < tracked.length; index += 1) {
    const segment = tracked[index]!
    for (const point of [segment.start, segment.end]) {
      const key = mapPointKey(point)
      const edgeIndexes = edgesAtVertex.get(key) ?? []
      edgeIndexes.push(index)
      edgesAtVertex.set(key, edgeIndexes)
    }
  }

  const polylines: MapPoint[][] = []

  const growChain = (chain: MapPoint[], fromHead: boolean): void => {
    while (true) {
      const tip = fromHead ? chain[0]! : chain[chain.length - 1]!
      const tipKey = mapPointKey(tip)
      const edgeIndexes = edgesAtVertex.get(tipKey) ?? []
      const nextEdgeIndex = edgeIndexes.find((index) => !tracked[index]!.used)
      if (nextEdgeIndex == null) break

      const nextEdge = tracked[nextEdgeIndex]!
      nextEdge.used = true
      const nextPoint =
        mapPointKey(nextEdge.start) === tipKey ? nextEdge.end : nextEdge.start
      if (fromHead) {
        chain.unshift(nextPoint)
      } else {
        chain.push(nextPoint)
      }
    }
  }

  for (let index = 0; index < tracked.length; index += 1) {
    const seed = tracked[index]!
    if (seed.used) continue
    seed.used = true

    const chain: MapPoint[] = [seed.start, seed.end]
    growChain(chain, false)
    growChain(chain, true)

    if (chain.length >= 2) {
      polylines.push(chain)
    }
  }

  return polylines
}

function joinNearbyPolylines(polylines: MapPoint[][], maxGap: number): MapPoint[][] {
  if (polylines.length <= 1 || maxGap <= 0) return polylines

  type Chain = { points: MapPoint[]; used: boolean }
  const chains: Chain[] = polylines.map((points) => ({ points: [...points], used: false }))
  const joined: MapPoint[][] = []

  const endpointDistance = (a: MapPoint, b: MapPoint): number => Math.hypot(a.x - b.x, a.y - b.y)

  for (let index = 0; index < chains.length; index += 1) {
    const seed = chains[index]!
    if (seed.used || seed.points.length < 2) continue
    seed.used = true

    let chain = seed.points
    let extended = true
    while (extended) {
      extended = false
      for (const candidate of chains) {
        if (candidate.used || candidate.points.length < 2) continue

        const head = chain[0]!
        const tail = chain[chain.length - 1]!
        const candidateHead = candidate.points[0]!
        const candidateTail = candidate.points[candidate.points.length - 1]!

        if (endpointDistance(tail, candidateHead) <= maxGap) {
          chain = [...chain, ...candidate.points.slice(1)]
          candidate.used = true
          extended = true
        } else if (endpointDistance(tail, candidateTail) <= maxGap) {
          chain = [...chain, ...candidate.points.slice(0, -1).reverse()]
          candidate.used = true
          extended = true
        } else if (endpointDistance(head, candidateTail) <= maxGap) {
          chain = [...candidate.points.slice(0, -1), ...chain]
          candidate.used = true
          extended = true
        } else if (endpointDistance(head, candidateHead) <= maxGap) {
          chain = [...candidate.points.slice(1).reverse(), ...chain]
          candidate.used = true
          extended = true
        }
      }
    }

    joined.push(chain)
  }

  return joined
}

export function nebulaBoundaryPolylinesFromGrid(
  grid: DensityGrid,
  centers: readonly NebulaCloudCenter[],
  threshold: number = NEBULA_BOUNDARY_DENSITY_THRESHOLD
): MapPoint[][] {
  return contourPolylinesFromSegments(grid, nebulaBoundarySegmentsFromGrid(grid, centers, threshold))
}

/** Stitch and join marching-squares segments into closed polylines. */
export function contourPolylinesFromSegments(
  grid: Pick<DensityGrid, 'step'>,
  segments: readonly MapSegment[]
): MapPoint[][] {
  const mergeTolerance = Math.max(grid.step * 0.05, 1e-4)
  const joinGap = grid.step * 0.95
  const stitched = stitchMapSegmentsToPolylines(segments, mergeTolerance)
  return joinNearbyPolylines(stitched, joinGap)
}

export function nebulaBoundaryPathFromSegments(
  segments: readonly MapSegment[],
  viewport: NebulaCloudViewport,
  mergeTolerance = 0
): string {
  return nebulaBoundaryPathFromPolylines(stitchMapSegmentsToPolylines(segments, mergeTolerance), viewport)
}

/** Marching squares contour projected to pane pixels (legacy helper for tests). */
export function nebulaBoundaryPathFromGrid(
  grid: DensityGrid,
  centers: readonly NebulaCloudCenter[],
  viewport: NebulaCloudViewport,
  threshold: number = NEBULA_BOUNDARY_DENSITY_THRESHOLD
): string {
  const segments = nebulaBoundarySegmentsFromGrid(grid, centers, threshold)
  const mergeTolerance = Math.max(grid.step * 0.05, 1e-4)
  return nebulaBoundaryPathFromSegments(segments, viewport, mergeTolerance)
}

function centersSignature(name: string, centers: readonly NebulaCloudCenter[]): string {
  return `boundary-v15-sparse-200:${name}:${centers
    .map((center) => `${center.x},${center.y},${center.radius},${center.intensity}`)
    .join('|')}`
}

type NebulaCloudRasterResult = {
  imageDataUrl: string
  alpha: Uint8ClampedArray
  rasterW: number
  rasterH: number
  stepX: number
  stepY: number
}

export function buildBoundaryGridFromRasterAlpha(
  raster: Pick<NebulaCloudRasterResult, 'alpha' | 'rasterW' | 'rasterH' | 'stepX' | 'stepY'>,
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
  alphaThreshold = 1
): DensityGrid {
  const pad = 1
  const cols = raster.rasterW + pad * 2
  const rows = raster.rasterH + pad * 2
  const step = Math.min(raster.stepX, raster.stepY)
  const values = new Float32Array(cols * rows)
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const px = col - pad
      const py = row - pad
      let alpha = 0
      if (px >= 0 && py >= 0 && px < raster.rasterW && py < raster.rasterH) {
        alpha = raster.alpha[(py * raster.rasterW + px) * 4 + 3] ?? 0
      }
      values[row * cols + col] = alpha >= alphaThreshold ? 1 : 0
    }
  }
  return {
    values,
    cols,
    rows,
    minX: bounds.minX - pad * raster.stepX,
    minY: bounds.minY - pad * raster.stepY,
    step,
  }
}

function rasterizeNebulaCloudMapSpace(
  centers: readonly NebulaCloudCenter[],
  bounds: { minX: number; minY: number; maxX: number; maxY: number }
): NebulaCloudRasterResult | null {
  const [r, g, b] = NEBULA_CLOUD_COLOR_RGB
  return rasterizeMapField(bounds, NEBULA_MAX_RASTER_PX, (mapX, mapY) => {
    const { cellX, cellY } = mapLyToSampleCell(mapX, mapY)
    const hostDensity = nebulaHostDensityAt(centers, cellX, cellY)
    let alpha = 0
    if (hostDensity > 0) {
      alpha = Math.round(
        Math.min(1, nebulaCloudFillOpacityAt(hostDensity, cellX, cellY)) * 255
      )
    }
    return { r, g, b, a: alpha }
  })
}

function getOrBuildNebulaCloudRasterCache(
  name: string,
  centers: readonly NebulaCloudCenter[]
): NebulaCloudRasterCache | null {
  if (centers.length === 0) return null

  const signature = centersSignature(name, centers)
  const cached = rasterCache.get(signature)
  if (cached != null) return cached

  const bounds = mapBoundsFromCircles(centers)
  if (bounds == null) return null

  const raster = rasterizeNebulaCloudMapSpace(centers, bounds)
  if (raster == null) return null

  const entry: NebulaCloudRasterCache = {
    signature,
    bounds,
    imageDataUrl: raster.imageDataUrl,
  }
  rasterCache.set(signature, entry)
  return entry
}

export function buildNebulaCloudPaneShape(
  name: string,
  centers: readonly NebulaCloudCenter[],
  viewport: NebulaCloudViewport
): NebulaCloudPaneShape | null {
  const cache = getOrBuildNebulaCloudRasterCache(name, centers)
  if (cache == null) return null
  if (
    !boundsIntersectsViewport(
      cache.bounds.minX,
      cache.bounds.minY,
      cache.bounds.maxX,
      cache.bounds.maxY,
      viewport
    )
  ) {
    return null
  }

  const { left, top, width, height } = paneRectFromBounds(cache.bounds, viewport)
  const key = `neb-cloud-${name}`

  return {
    key,
    left,
    top,
    width,
    height,
    imageDataUrl: cache.imageDataUrl,
    boundaryPath: nebulaBoundaryPathFromCenters(centers, viewport),
    fillClipPathId: `${key}-fill-clip`,
    stroke: NEBULA_STROKE_COLOR,
    strokeWidth: NEBULA_STROKE_WIDTH,
  }
}

export function buildNebulaCloudPaneShapes(
  circles: readonly NebulaOverlayCircle[],
  viewport: NebulaCloudViewport
): NebulaCloudPaneShape[] {
  const grouped = groupNebulaCentersByName(circles)
  const activeSignatures = new Set<string>()
  for (const [name, centers] of grouped) {
    activeSignatures.add(centersSignature(name, centers))
  }
  for (const signature of rasterCache.keys()) {
    if (!activeSignatures.has(signature)) {
      rasterCache.delete(signature)
    }
  }

  const shapes: NebulaCloudPaneShape[] = []
  for (const [name, centers] of grouped) {
    const shape = buildNebulaCloudPaneShape(name, centers, viewport)
    if (shape != null) shapes.push(shape)
  }
  return shapes
}
