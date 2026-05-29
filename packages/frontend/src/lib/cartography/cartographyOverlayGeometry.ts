import { PLANET_CELL_CENTER_OFFSET } from '../planetSpatialGrid'

export type CartographyOverlayViewport = {
  width: number
  height: number
  tx: number
  ty: number
  scale: number
}

export type MapBounds = {
  minX: number
  minY: number
  maxX: number
  maxY: number
}

export type MapPoint = { x: number; y: number }

export type MapCircle = {
  x: number
  y: number
  radius: number
}

export function mapLyToFlow(mapX: number, mapY: number): { cx: number; cy: number } {
  return { cx: mapX, cy: -mapY }
}

/** Integer game map cell coordinates to React Flow center (y grows downward). */
export function gameMapCellCenterToFlow(gx: number, gy: number): { cx: number; cy: number } {
  return mapLyToFlow(gx + PLANET_CELL_CENTER_OFFSET, gy + PLANET_CELL_CENTER_OFFSET)
}

export function flowToPane(
  cx: number,
  cy: number,
  viewport: CartographyOverlayViewport
): { px: number; py: number } {
  return {
    px: cx * viewport.scale + viewport.tx,
    py: cy * viewport.scale + viewport.ty,
  }
}

export function mapToPane(
  mapX: number,
  mapY: number,
  viewport: CartographyOverlayViewport
): { px: number; py: number } {
  const { cx, cy } = mapLyToFlow(mapX, mapY)
  return flowToPane(cx, cy, viewport)
}

export function mapBoundsFromCircles(circles: readonly MapCircle[]): MapBounds | null {
  if (circles.length === 0) return null
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (const circle of circles) {
    minX = Math.min(minX, circle.x - circle.radius)
    minY = Math.min(minY, circle.y - circle.radius)
    maxX = Math.max(maxX, circle.x + circle.radius)
    maxY = Math.max(maxY, circle.y + circle.radius)
  }
  return { minX, minY, maxX, maxY }
}

export function boundsIntersectsViewport(
  minX: number,
  minY: number,
  maxX: number,
  maxY: number,
  viewport: CartographyOverlayViewport
): boolean {
  const corners = [
    mapToPane(minX, minY, viewport),
    mapToPane(maxX, minY, viewport),
    mapToPane(minX, maxY, viewport),
    mapToPane(maxX, maxY, viewport),
  ]
  const paneMinX = Math.min(...corners.map((corner) => corner.px))
  const paneMaxX = Math.max(...corners.map((corner) => corner.px))
  const paneMinY = Math.min(...corners.map((corner) => corner.py))
  const paneMaxY = Math.max(...corners.map((corner) => corner.py))
  return paneMaxX >= 0 && paneMinX <= viewport.width && paneMaxY >= 0 && paneMinY <= viewport.height
}

export function paneRectFromBounds(
  bounds: MapBounds,
  viewport: CartographyOverlayViewport
): { left: number; top: number; width: number; height: number } {
  const topLeft = mapToPane(bounds.minX, bounds.maxY, viewport)
  const bottomRight = mapToPane(bounds.maxX, bounds.minY, viewport)
  const left = Math.min(topLeft.px, bottomRight.px)
  const top = Math.min(topLeft.py, bottomRight.py)
  const width = Math.max(1, Math.abs(bottomRight.px - topLeft.px))
  const height = Math.max(1, Math.abs(bottomRight.py - topLeft.py))
  return { left, top, width, height }
}

export function scalarGridStepForBounds(bounds: MapBounds, maxCells: number): number {
  const span = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY, 1)
  return Math.max(1, span / maxCells)
}

export function computeRasterDimensions(
  bounds: MapBounds,
  maxRasterPx: number
): {
  rasterW: number
  rasterH: number
  stepX: number
  stepY: number
  widthLy: number
  heightLy: number
} {
  const widthLy = Math.max(bounds.maxX - bounds.minX, 1)
  const heightLy = Math.max(bounds.maxY - bounds.minY, 1)
  let rasterW = Math.max(1, Math.ceil(widthLy))
  let rasterH = Math.max(1, Math.ceil(heightLy))
  const maxDim = Math.max(rasterW, rasterH)
  if (maxDim > maxRasterPx) {
    const scale = maxRasterPx / maxDim
    rasterW = Math.max(1, Math.round(rasterW * scale))
    rasterH = Math.max(1, Math.round(rasterH * scale))
  }
  return {
    rasterW,
    rasterH,
    stepX: widthLy / rasterW,
    stepY: heightLy / rasterH,
    widthLy,
    heightLy,
  }
}

/** Map row 0 of a raster PNG to the north edge (bounds.maxY). */
export function mapPointFromRasterPixel(
  bounds: MapBounds,
  px: number,
  py: number,
  stepX: number,
  stepY: number
): { mapX: number; mapY: number } {
  return {
    mapX: bounds.minX + (px + 0.5) * stepX,
    mapY: bounds.maxY - (py + 0.5) * stepY,
  }
}

export function maxSearchRadiusFromCircles(origin: MapPoint, circles: readonly MapCircle[]): number {
  let maxRadius = 0
  for (const circle of circles) {
    const distToCenter = Math.hypot(circle.x - origin.x, circle.y - origin.y)
    maxRadius = Math.max(maxRadius, distToCenter + circle.radius)
  }
  return maxRadius + 1
}

function mapPointKey(point: MapPoint): string {
  return `${point.x.toFixed(6)},${point.y.toFixed(6)}`
}

export function formatPaneCoordinate(value: number): string {
  return (Math.round(value * 100) / 100).toFixed(2)
}

export function closeSvgPath(path: string): string {
  if (path.length > 0 && !path.endsWith(' Z')) {
    return `${path} Z`
  }
  return path
}

export function mapPolylineToPanePath(
  polyline: readonly MapPoint[],
  viewport: CartographyOverlayViewport
): string {
  if (polyline.length < 2) return ''

  const first = polyline[0]!
  const last = polyline[polyline.length - 1]!
  const closed =
    polyline.length >= 3 &&
    (first === last ||
      mapPointKey(first) === mapPointKey(last) ||
      Math.hypot(first.x - last.x, first.y - last.y) < 1e-6)

  const drawPoints =
    closed && first === last ? polyline.slice(0, -1) : closed ? polyline : polyline

  const panePoints = drawPoints.map((point) => mapToPane(point.x, point.y, viewport))
  if (panePoints.length < 2) return ''

  const [paneFirst, ...paneRest] = panePoints
  if (paneFirst == null) return ''

  let path =
    `M ${formatPaneCoordinate(paneFirst.px)} ${formatPaneCoordinate(paneFirst.py)}` +
    paneRest
      .map((point) => ` L ${formatPaneCoordinate(point.px)} ${formatPaneCoordinate(point.py)}`)
      .join('')
  if (closed) {
    path += ' Z'
  }
  return path
}

export function boundaryPathFromMapPolygons(
  polygons: readonly (readonly MapPoint[])[],
  viewport: CartographyOverlayViewport
): string {
  if (polygons.length === 0) return ''
  return polygons
    .map((polyline) => mapPolylineToPanePath(polyline, viewport))
    .filter((path) => path.length > 0)
    .join(' ')
}

export function boundaryPathsFromMapPolygons(
  polygons: readonly (readonly MapPoint[])[],
  viewport: CartographyOverlayViewport
): string[] {
  return polygons
    .map((polyline) => closeSvgPath(mapPolylineToPanePath(polyline, viewport)))
    .filter((path) => path.length > 0)
}

/** Ray-cast test for a closed boundary polygon in map coordinates. */
export function isPointInsideMapPolygon(
  mapX: number,
  mapY: number,
  polygon: readonly MapPoint[]
): boolean {
  if (polygon.length < 3) return false

  let inside = false
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index, index += 1) {
    const current = polygon[index]!
    const prior = polygon[previous]!
    const intersects =
      (current.y > mapY) !== (prior.y > mapY) &&
      mapX < ((prior.x - current.x) * (mapY - current.y)) / (prior.y - current.y) + current.x
    if (intersects) inside = !inside
  }
  return inside
}
