import type { IonStormOverlayCircle } from '../api/bff'
import {
  boundaryPathsFromMapPolygons,
  boundsIntersectsViewport,
  mapBoundsFromCircles,
  maxSearchRadiusFromCircles,
  paneRectFromBounds,
  scalarGridStepForBounds,
  type CartographyOverlayViewport,
  type MapPoint,
} from './cartographyOverlayGeometry'
import { boundaryPolygonFromOrigin } from './isoContourRayMarch'
import {
  buildScalarGrid,
  findComponentsInGrid,
  gridValueAt,
  type DensityGrid,
  type ScalarFieldComponent,
} from './scalarFieldGrid'
import { rasterizeMapField } from './rasterizeMapField'
import {
  ION_STORM_BOUNDARY_MAX_GRID_CELLS,
  ION_STORM_BOUNDARY_RAY_COUNT,
  ION_STORM_BOUNDARY_STROKE_WIDTH,
  ION_STORM_CLASS_VOLTAGE_THRESHOLDS,
  ION_STORM_MAX_RASTER_PX,
  ION_STORM_OUTER_VOLTAGE_THRESHOLD,
  ionStormClassFromVoltage,
  ionStormFillOpacity,
  ionStormRimOpacity,
  ionStormStrokeColor,
} from './stellarCartographyTheme'

export type IonStormCloudViewport = CartographyOverlayViewport
export type IonStormComponent = ScalarFieldComponent

export type IonStormCircle = {
  x: number
  y: number
  radius: number
  voltage: number
}

export type IonStormClassBoundaryPath = {
  stormClass: number
  path: string
  stroke: string
}

export type IonStormCloudPaneShape = {
  key: string
  left: number
  top: number
  width: number
  height: number
  imageDataUrl: string
  fillClipPathId: string
  outerBoundaryPaths: string[]
  outerStroke: string
  classBoundaryPaths: IonStormClassBoundaryPath[]
  strokeWidth: number
}

type IonStormRasterCache = {
  signature: string
  bounds: { minX: number; minY: number; maxX: number; maxY: number }
  imageDataUrl: string
}

const rasterCache = new Map<string, IonStormRasterCache>()

export function clearIonStormCloudRasterCache(): void {
  rasterCache.clear()
}

function hexToRgb(hex: string): [number, number, number] {
  const value = parseInt(hex.slice(1), 16)
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255]
}

function hexWithAlpha(hex: string, alpha: number): string {
  const [r, g, b] = hexToRgb(hex)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** Summed ion voltage at a map point; matches Core sample_at. */
export function ionVoltageAt(
  circles: readonly IonStormCircle[],
  mapX: number,
  mapY: number,
  cloudy: boolean
): number {
  if (circles.length === 0) return 0
  if (!cloudy) {
    const center = circles[0]!
    if (center.radius <= 0) return 0
    const dist = Math.hypot(mapX - center.x, mapY - center.y)
    return dist <= center.radius ? center.voltage : 0
  }

  let total = 0
  for (const circle of circles) {
    if (circle.radius <= 0) continue
    const dist = Math.hypot(mapX - circle.x, mapY - circle.y)
    if (dist <= circle.radius) {
      total += circle.voltage * (1 - dist / circle.radius)
    }
  }
  return total
}

export function groupIonStormsByRoot(
  circles: readonly IonStormOverlayCircle[]
): Map<number, { root: IonStormOverlayCircle; circles: IonStormCircle[] }> {
  const byId = new Map<number, IonStormOverlayCircle>()
  for (const circle of circles) {
    const numericId = Number.parseInt(circle.id.replace(/^is-/, ''), 10)
    if (Number.isFinite(numericId)) {
      byId.set(numericId, circle)
    }
  }

  const grouped = new Map<number, { root: IonStormOverlayCircle; circles: IonStormCircle[] }>()
  for (const circle of circles) {
    const parentId = circle.parentId ?? 0
    if (parentId !== 0) continue

    const rootNumericId = Number.parseInt(circle.id.replace(/^is-/, ''), 10)
    const stormCircles: IonStormCircle[] = []
    const appendCircle = (entry: IonStormOverlayCircle) => {
      stormCircles.push({
        x: entry.x,
        y: entry.y,
        radius: entry.radius,
        voltage: entry.voltage ?? 0,
      })
    }
    appendCircle(circle)
    for (const subCircle of byId.values()) {
      if (subCircle.parentId === rootNumericId) {
        appendCircle(subCircle)
      }
    }
    grouped.set(rootNumericId, { root: circle, circles: stormCircles })
  }
  return grouped
}

function maxVoltageInGroup(circles: readonly IonStormCircle[], cloudy: boolean): number {
  let maxVoltage = 0
  for (const circle of circles) {
    maxVoltage = Math.max(maxVoltage, ionVoltageAt(circles, circle.x, circle.y, cloudy))
  }
  return maxVoltage
}

/** Sampled voltage field for connected-component detection before ray marching. */
export function buildIonVoltageGrid(
  circles: readonly IonStormCircle[],
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
  step: number,
  cloudy: boolean
): DensityGrid {
  return buildScalarGrid(bounds, step, (mapX, mapY) => ionVoltageAt(circles, mapX, mapY, cloudy))
}

function gridClassAt(grid: DensityGrid, col: number, row: number): number {
  const voltage = gridValueAt(grid, col, row)
  if (voltage <= 0) return 0
  return ionStormClassFromVoltage(Math.round(voltage))
}

/** Components where sampled voltage >= threshold (outer storm edge). */
export function findComponentsAtThreshold(grid: DensityGrid, threshold: number): IonStormComponent[] {
  return findComponentsInGrid(grid, (col, row) => gridValueAt(grid, col, row) >= threshold)
}

/** Components where discrete hazard class >= minClass (matches raster fill). */
export function findComponentsAtMinClass(grid: DensityGrid, minClass: number): IonStormComponent[] {
  return findComponentsInGrid(grid, (col, row) => gridClassAt(grid, col, row) >= minClass)
}

/** Smooth closed iso-contour from one interior anchor (512-ray polygon). */
export function ionStormBoundaryPolygonFromOrigin(
  circles: readonly IonStormCircle[],
  cloudy: boolean,
  threshold: number,
  origin: MapPoint,
  maxSearchRadius: number,
  rayCount: number = ION_STORM_BOUNDARY_RAY_COUNT
): MapPoint[] {
  const globalMaxRadius = maxSearchRadiusFromCircles(origin, circles)
  const fieldAt = (mapX: number, mapY: number): number => ionVoltageAt(circles, mapX, mapY, cloudy)
  return boundaryPolygonFromOrigin(
    origin,
    fieldAt,
    threshold,
    maxSearchRadius,
    globalMaxRadius,
    rayCount
  )
}

function ionStormBoundaryPolygonsForComponents(
  circles: readonly IonStormCircle[],
  cloudy: boolean,
  threshold: number,
  components: readonly IonStormComponent[]
): MapPoint[][] {
  return components
    .map((component) =>
      ionStormBoundaryPolygonFromOrigin(
        circles,
        cloudy,
        threshold,
        component.origin,
        component.maxSearchRadius
      )
    )
    .filter((polygon) => polygon.length >= 3)
}

/** All iso-contours at a threshold: one ray-marched polygon per disjoint component. */
export function ionStormBoundaryPolygonsAtThreshold(
  circles: readonly IonStormCircle[],
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
  cloudy: boolean,
  threshold: number,
  grid?: DensityGrid,
  components?: readonly IonStormComponent[]
): MapPoint[][] {
  if (maxVoltageInGroup(circles, cloudy) < threshold) return []

  const gridStep = scalarGridStepForBounds(bounds, ION_STORM_BOUNDARY_MAX_GRID_CELLS)
  const voltageGrid = grid ?? buildIonVoltageGrid(circles, bounds, gridStep, cloudy)
  const resolvedComponents =
    components ??
    (threshold === ION_STORM_OUTER_VOLTAGE_THRESHOLD
      ? findComponentsAtThreshold(voltageGrid, threshold)
      : findComponentsAtMinClass(voltageGrid, ionStormClassFromVoltage(threshold)))

  return ionStormBoundaryPolygonsForComponents(
    circles,
    cloudy,
    threshold,
    resolvedComponents
  )
}

export function ionStormBoundaryPathFromPolygons(
  polygons: readonly MapPoint[][],
  viewport: IonStormCloudViewport
): string[] {
  return boundaryPathsFromMapPolygons(polygons, viewport)
}

function ionStormBoundaryPathsAtThreshold(
  circles: readonly IonStormCircle[],
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
  viewport: IonStormCloudViewport,
  cloudy: boolean,
  threshold: number,
  grid: DensityGrid
): string[] {
  return ionStormBoundaryPathFromPolygons(
    ionStormBoundaryPolygonsAtThreshold(circles, bounds, cloudy, threshold, grid),
    viewport
  )
}

function buildClassBoundaryPaths(
  grid: DensityGrid,
  circles: readonly IonStormCircle[],
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
  viewport: IonStormCloudViewport,
  cloudy: boolean
): IonStormClassBoundaryPath[] {
  if (!cloudy) return []

  const maxVoltage = maxVoltageInGroup(circles, cloudy)
  const paths: IonStormClassBoundaryPath[] = []

  for (const threshold of ION_STORM_CLASS_VOLTAGE_THRESHOLDS) {
    if (maxVoltage < threshold) continue
    const stormClass = ionStormClassFromVoltage(threshold)
    const stroke = hexWithAlpha(ionStormStrokeColor(stormClass), ionStormRimOpacity(stormClass))
    const boundaryPaths = ionStormBoundaryPathsAtThreshold(
      circles,
      bounds,
      viewport,
      cloudy,
      threshold,
      grid
    )
    for (const path of boundaryPaths) {
      paths.push({
        stormClass,
        path,
        stroke,
      })
    }
  }

  return paths
}

function stormSignature(rootId: number, circles: readonly IonStormCircle[], cloudy: boolean): string {
  return `ion-v4-bounded:${cloudy ? 'cloudy' : 'classic'}:${rootId}:${circles
    .map((circle) => `${circle.x},${circle.y},${circle.radius},${circle.voltage}`)
    .join('|')}`
}

function rasterizeIonStormMapSpace(
  circles: readonly IonStormCircle[],
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
  cloudy: boolean
): { imageDataUrl: string } | null {
  const raster = rasterizeMapField(bounds, ION_STORM_MAX_RASTER_PX, (mapX, mapY) => {
    const voltage = ionVoltageAt(circles, mapX, mapY, cloudy)
    if (voltage <= 0) {
      return { r: 0, g: 0, b: 0, a: 0 }
    }
    const stormClass = ionStormClassFromVoltage(Math.round(voltage))
    const color = ionStormStrokeColor(stormClass)
    const [r, g, b] = hexToRgb(color)
    const alpha = Math.round(Math.min(1, ionStormFillOpacity(stormClass)) * 255)
    return { r, g, b, a: alpha }
  })
  return raster != null ? { imageDataUrl: raster.imageDataUrl } : null
}

function getOrBuildIonStormRasterCache(
  rootId: number,
  circles: readonly IonStormCircle[],
  cloudy: boolean
): IonStormRasterCache | null {
  if (circles.length === 0) return null

  const signature = stormSignature(rootId, circles, cloudy)
  const cached = rasterCache.get(signature)
  if (cached != null) return cached

  const bounds = mapBoundsFromCircles(circles)
  if (bounds == null) return null

  const raster = rasterizeIonStormMapSpace(circles, bounds, cloudy)
  if (raster == null) return null

  const entry: IonStormRasterCache = {
    signature,
    bounds,
    imageDataUrl: raster.imageDataUrl,
  }
  rasterCache.set(signature, entry)
  return entry
}

export function buildIonStormCloudPaneShape(
  rootId: number,
  circles: readonly IonStormCircle[],
  viewport: IonStormCloudViewport,
  cloudy: boolean
): IonStormCloudPaneShape | null {
  const cache = getOrBuildIonStormRasterCache(rootId, circles, cloudy)
  if (cache == null) return null
  if (!boundsIntersectsViewport(cache.bounds.minX, cache.bounds.minY, cache.bounds.maxX, cache.bounds.maxY, viewport)) {
    return null
  }

  const { left, top, width, height } = paneRectFromBounds(cache.bounds, viewport)
  const key = `ion-cloud-${rootId}`
  const gridStep = scalarGridStepForBounds(cache.bounds, ION_STORM_BOUNDARY_MAX_GRID_CELLS)
  const voltageGrid = buildIonVoltageGrid(circles, cache.bounds, gridStep, cloudy)
  const outerBoundaryPaths = ionStormBoundaryPathsAtThreshold(
    circles,
    cache.bounds,
    viewport,
    cloudy,
    ION_STORM_OUTER_VOLTAGE_THRESHOLD,
    voltageGrid
  )
  const outerClass = ionStormClassFromVoltage(
    Math.round(maxVoltageInGroup(circles, cloudy))
  )

  return {
    key,
    left,
    top,
    width,
    height,
    imageDataUrl: cache.imageDataUrl,
    fillClipPathId: `${key}-fill-clip`,
    outerBoundaryPaths,
    outerStroke: hexWithAlpha(ionStormStrokeColor(outerClass), ionStormRimOpacity(outerClass)),
    classBoundaryPaths: buildClassBoundaryPaths(
      voltageGrid,
      circles,
      cache.bounds,
      viewport,
      cloudy
    ),
    strokeWidth: ION_STORM_BOUNDARY_STROKE_WIDTH,
  }
}

export function buildIonStormCloudPaneShapes(
  circles: readonly IonStormOverlayCircle[],
  viewport: IonStormCloudViewport,
  cloudy: boolean
): IonStormCloudPaneShape[] {
  const grouped = groupIonStormsByRoot(circles)
  const activeSignatures = new Set<string>()
  const shapes: IonStormCloudPaneShape[] = []

  for (const [rootId, group] of grouped) {
    activeSignatures.add(stormSignature(rootId, group.circles, cloudy))
    const shape = buildIonStormCloudPaneShape(rootId, group.circles, viewport, cloudy)
    if (shape != null) shapes.push(shape)
  }

  for (const signature of rasterCache.keys()) {
    if (!activeSignatures.has(signature)) {
      rasterCache.delete(signature)
    }
  }

  return shapes
}
