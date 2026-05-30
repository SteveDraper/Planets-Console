import type { MapPoint } from './cartographyOverlayGeometry'

export const DEFAULT_ISO_CONTOUR_RAY_COUNT = 512

const BOUNDARY_SEARCH_ITERATIONS = 48

export type ScalarFieldAt = (mapX: number, mapY: number) => number

export function boundaryPointOnRay(
  origin: MapPoint,
  angle: number,
  fieldAt: ScalarFieldAt,
  threshold: number,
  maxRadius: number
): MapPoint | null {
  const dx = Math.cos(angle)
  const dy = Math.sin(angle)
  const valueOnRay = (radius: number): number =>
    fieldAt(origin.x + radius * dx, origin.y + radius * dy)

  if (valueOnRay(maxRadius) >= threshold) return null

  let lo = 0
  let hi = maxRadius
  for (let iteration = 0; iteration < BOUNDARY_SEARCH_ITERATIONS; iteration += 1) {
    const mid = (lo + hi) / 2
    if (valueOnRay(mid) >= threshold) {
      lo = mid
    } else {
      hi = mid
    }
  }

  return {
    x: origin.x + hi * dx,
    y: origin.y + hi * dy,
  }
}

/** Smooth closed iso-contour from one interior anchor (512-ray polygon by default). */
export function boundaryPolygonFromOrigin(
  origin: MapPoint,
  fieldAt: ScalarFieldAt,
  threshold: number,
  maxSearchRadius: number,
  globalMaxSearchRadius: number,
  rayCount: number = DEFAULT_ISO_CONTOUR_RAY_COUNT
): MapPoint[] {
  let maxRadius = Math.min(maxSearchRadius, globalMaxSearchRadius)
  const polygon: MapPoint[] = []

  for (let attempt = 0; attempt < 6; attempt += 1) {
    polygon.length = 0
    for (let index = 0; index < rayCount; index += 1) {
      const angle = (2 * Math.PI * index) / rayCount
      const point = boundaryPointOnRay(origin, angle, fieldAt, threshold, maxRadius)
      if (point != null) {
        polygon.push(point)
      }
    }
    if (polygon.length >= 3) {
      return polygon
    }
    maxRadius = Math.min(globalMaxSearchRadius, maxRadius * 1.5 + 1)
  }

  return polygon
}
