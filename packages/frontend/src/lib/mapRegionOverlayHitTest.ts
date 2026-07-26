/**
 * Hit-test map region overlays (closed boundary paths + optional disks)
 * and collect ``hoverSummary`` strings for map tooltips.
 *
 * Boundary hit-test is geometry-complete for shared line|arc closed paths:
 * arcs are flattened to polylines, then even-odd ray casting decides interior.
 */

import type {
  MapRegionBoundaryArcEdge,
  MapRegionBoundaryGeometry,
  MapRegionOverlay,
  MapRegionOverlayDisk,
  MapRegionOverlayVertex,
} from '../api/mapRegionOverlayTypes'

const ANGLE_EPS = 1e-9
const RADIUS_EPS = 1e-6

/**
 * Max chord sagitta (map ly) when approximating arcs as polylines for hit-test.
 * At r=200 this yields ~5.7° steps; hover UX, not CAD precision.
 */
const ARC_SAMPLE_MAX_SAGITTA = 0.5
const ARC_SAMPLE_MAX_SEGMENTS = 128

export function pointInDisk(
  mapX: number,
  mapY: number,
  disk: MapRegionOverlayDisk
): boolean {
  const dx = mapX - disk.x
  const dy = mapY - disk.y
  return dx * dx + dy * dy <= disk.radius * disk.radius + RADIUS_EPS
}

/**
 * Signed sweep from ``startAngle`` to ``endAngle`` in map space (Y-up).
 * Positive = CCW, negative = CW. Full-circle when endpoints coincide.
 */
function arcSignedDelta(
  startAngle: number,
  endAngle: number,
  clockwise: boolean
): number {
  let delta = endAngle - startAngle
  if (clockwise) {
    while (delta >= 0) delta -= 2 * Math.PI
  } else {
    while (delta <= 0) delta += 2 * Math.PI
  }
  return delta
}

function arcSampleCount(radius: number, absDelta: number): number {
  if (absDelta <= ANGLE_EPS) return 1
  const r = Math.max(radius, ARC_SAMPLE_MAX_SAGITTA)
  const cosHalf = 1 - ARC_SAMPLE_MAX_SAGITTA / r
  const maxStep =
    cosHalf >= 1 ? Math.PI : 2 * Math.acos(Math.max(-1, Math.min(1, cosHalf)))
  const count = Math.ceil(absDelta / Math.max(maxStep, ANGLE_EPS))
  return Math.min(ARC_SAMPLE_MAX_SEGMENTS, Math.max(1, count))
}

/**
 * Intermediate + end vertices along an arc (excludes ``start``).
 * Map-space Y-up; ``clockwise`` matches wire / Core boundary arcs.
 */
function sampleArcVertices(
  start: MapRegionOverlayVertex,
  end: MapRegionOverlayVertex,
  arc: MapRegionBoundaryArcEdge
): MapRegionOverlayVertex[] {
  const radius = Math.hypot(start.x - arc.centerX, start.y - arc.centerY)
  if (!(radius > RADIUS_EPS)) return [{ x: end.x, y: end.y }]

  const startAngle = Math.atan2(start.y - arc.centerY, start.x - arc.centerX)
  const endAngle = Math.atan2(end.y - arc.centerY, end.x - arc.centerX)
  const delta = arcSignedDelta(startAngle, endAngle, arc.clockwise)
  const segments = arcSampleCount(radius, Math.abs(delta))
  const points: MapRegionOverlayVertex[] = []
  for (let i = 1; i < segments; i++) {
    const t = i / segments
    const angle = startAngle + delta * t
    points.push({
      x: arc.centerX + radius * Math.cos(angle),
      y: arc.centerY + radius * Math.sin(angle),
    })
  }
  points.push({ x: end.x, y: end.y })
  return points
}

/**
 * Flatten closed boundary geometry to a polyline ring (open: last ≠ first;
 * ray cast closes last→first). Returns null when the path is too short or
 * edges/vertices disagree.
 */
export function boundaryGeometryToPolyline(
  geometry: MapRegionBoundaryGeometry
): MapRegionOverlayVertex[] | null {
  const { vertices, edges } = geometry
  if (vertices.length < 3 || edges.length !== vertices.length) return null

  const ring: MapRegionOverlayVertex[] = [{ x: vertices[0]!.x, y: vertices[0]!.y }]
  for (let i = 0; i < edges.length; i++) {
    const start = vertices[i]!
    const end = vertices[(i + 1) % vertices.length]!
    const edge = edges[i]!
    if (edge.type === 'line') {
      ring.push({ x: end.x, y: end.y })
      continue
    }
    if (edge.type !== 'arc') return null
    ring.push(...sampleArcVertices(start, end, edge))
  }

  // Drop duplicate close vertex if the last edge already re-emitted vertex 0.
  const last = ring[ring.length - 1]!
  const first = ring[0]!
  if (
    ring.length > 1 &&
    Math.abs(last.x - first.x) <= RADIUS_EPS &&
    Math.abs(last.y - first.y) <= RADIUS_EPS
  ) {
    ring.pop()
  }
  return ring.length >= 3 ? ring : null
}

/** Even-odd ray cast; ``ring`` is open (last edge implied back to first). */
export function pointInPolylineRing(
  mapX: number,
  mapY: number,
  ring: readonly MapRegionOverlayVertex[]
): boolean {
  let inside = false
  const n = ring.length
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = ring[i]!.x
    const yi = ring[i]!.y
    const xj = ring[j]!.x
    const yj = ring[j]!.y
    if (yi === yj) continue
    if ((yi > mapY) === (yj > mapY)) continue
    const xIntersect = ((xj - xi) * (mapY - yi)) / (yj - yi) + xi
    if (mapX < xIntersect) inside = !inside
  }
  return inside
}

/**
 * Point-in-boundary for general closed line|arc paths (any edge order).
 * Arcs are polyline-approximated (see ``ARC_SAMPLE_MAX_SAGITTA``).
 */
export function pointInBoundaryGeometry(
  mapX: number,
  mapY: number,
  geometry: MapRegionBoundaryGeometry
): boolean {
  const ring = boundaryGeometryToPolyline(geometry)
  if (ring == null) return false
  return pointInPolylineRing(mapX, mapY, ring)
}

export function pointHitsMapRegionOverlay(
  mapX: number,
  mapY: number,
  overlay: MapRegionOverlay
): boolean {
  const { geometry } = overlay
  if (geometry.type === 'boundary') {
    if (pointInBoundaryGeometry(mapX, mapY, geometry)) return true
    const disks = geometry.disks ?? []
    for (const disk of disks) {
      if (pointInDisk(mapX, mapY, disk)) return true
    }
    return false
  }
  // Coverage overlays: hit disks only (no homeworld hoverSummary today).
  for (const disk of geometry.disks) {
    if (pointInDisk(mapX, mapY, disk)) return true
  }
  return false
}

/**
 * Collect hoverSummary lines for overlays under ``(mapX, mapY)``.
 * Overlays without hoverSummary are skipped even if hit.
 */
export function collectRegionOverlayHoverSummaries(
  overlays: readonly MapRegionOverlay[],
  mapX: number,
  mapY: number
): string[] {
  const lines: string[] = []
  for (const overlay of overlays) {
    const summary = overlay.hoverSummary?.trim()
    if (summary == null || summary === '') continue
    if (!pointHitsMapRegionOverlay(mapX, mapY, overlay)) continue
    lines.push(summary)
  }
  return lines
}
