import {
  boundaryPathsFromMapPolygons,
  maxSearchRadiusFromCircles,
  scalarGridStepForBounds,
  type CartographyOverlayViewport,
  type MapBounds,
  type MapCircle,
  type MapPoint,
} from './cartographyOverlayGeometry'
import {
  boundaryPolygonFromOrigin,
  DEFAULT_ISO_CONTOUR_RAY_COUNT,
  type ScalarFieldAt,
} from './isoContourRayMarch'
import {
  buildScalarGrid,
  findComponentsInGrid,
  gridValueAt,
  type DensityGrid,
  type ScalarFieldComponent,
} from './scalarFieldGrid'

export type { ScalarFieldAt }

export type BoundaryPolygonsAtThresholdOptions = {
  grid?: DensityGrid
  components?: readonly ScalarFieldComponent[]
  rayCount?: number
  isActive?: (col: number, row: number, grid: DensityGrid) => boolean
}

/** Ray-marched iso-contours: one closed polygon per connected component above threshold. */
export function boundaryPolygonsAtThreshold(
  bounds: MapBounds,
  maxGridCells: number,
  fieldAt: ScalarFieldAt,
  threshold: number,
  searchCircles: readonly MapCircle[],
  options?: BoundaryPolygonsAtThresholdOptions
): MapPoint[][] {
  const gridStep = scalarGridStepForBounds(bounds, maxGridCells)
  const fieldGrid = options?.grid ?? buildScalarGrid(bounds, gridStep, fieldAt)
  const isActive =
    options?.isActive ??
    ((col, row, grid) => gridValueAt(grid, col, row) >= threshold)
  const resolvedComponents =
    options?.components ??
    findComponentsInGrid(fieldGrid, (col, row) => isActive(col, row, fieldGrid))
  const rayCount = options?.rayCount ?? DEFAULT_ISO_CONTOUR_RAY_COUNT

  return resolvedComponents
    .map((component) =>
      boundaryPolygonFromOrigin(
        component.origin,
        fieldAt,
        threshold,
        component.maxSearchRadius,
        maxSearchRadiusFromCircles(component.origin, searchCircles),
        rayCount
      )
    )
    .filter((polygon) => polygon.length >= 3)
}

export function boundaryPathsAtThreshold(
  bounds: MapBounds,
  viewport: CartographyOverlayViewport,
  maxGridCells: number,
  fieldAt: ScalarFieldAt,
  threshold: number,
  searchCircles: readonly MapCircle[],
  options?: BoundaryPolygonsAtThresholdOptions
): string[] {
  return boundaryPathsFromMapPolygons(
    boundaryPolygonsAtThreshold(
      bounds,
      maxGridCells,
      fieldAt,
      threshold,
      searchCircles,
      options
    ),
    viewport
  )
}
