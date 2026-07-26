/**
 * Hit-test map region overlays (boundary annular sectors + optional disks)
 * and collect ``hoverSummary`` strings for map tooltips.
 */

import type {
  MapRegionBoundaryGeometry,
  MapRegionOverlay,
  MapRegionOverlayDisk,
} from '../api/mapRegionOverlayTypes'

const ANGLE_EPS = 1e-9
const RADIUS_EPS = 1e-6

function normalizeAngleDelta(delta: number): number {
  let value = delta % (2 * Math.PI)
  if (value < 0) value += 2 * Math.PI
  return value
}

/** True when ``angle`` lies on the CCW arc from ``start`` to ``end`` (inclusive). */
export function angleInCounterClockwiseWedge(
  angle: number,
  start: number,
  end: number
): boolean {
  const span = normalizeAngleDelta(end - start)
  if (span <= ANGLE_EPS) {
    // Degenerate / full-circle wedge: treat as covering all angles.
    return span === 0 ? true : normalizeAngleDelta(angle - start) <= span + ANGLE_EPS
  }
  return normalizeAngleDelta(angle - start) <= span + ANGLE_EPS
}

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
 * Point-in-annular-sector for the Core homeworld boundary encoding:
 * outer CCW arc, radial line, inner CW arc, radial line.
 */
export function pointInAnnularSectorBoundary(
  mapX: number,
  mapY: number,
  geometry: MapRegionBoundaryGeometry
): boolean {
  const { vertices, edges } = geometry
  if (vertices.length < 4 || edges.length !== vertices.length) return false
  const outerArc = edges[0]
  if (outerArc == null || outerArc.type !== 'arc') return false

  const cx = outerArc.centerX
  const cy = outerArc.centerY
  const dist = Math.hypot(mapX - cx, mapY - cy)

  const outerStart = vertices[0]!
  const outerEnd = vertices[1]!
  const innerEnd = vertices[2]!
  const rOuter = Math.hypot(outerStart.x - cx, outerStart.y - cy)
  const rInner = Math.hypot(innerEnd.x - cx, innerEnd.y - cy)
  if (!(rOuter >= rInner)) return false
  if (dist < rInner - RADIUS_EPS || dist > rOuter + RADIUS_EPS) return false

  const angleStart = Math.atan2(outerStart.y - cy, outerStart.x - cx)
  const angleEnd = Math.atan2(outerEnd.y - cy, outerEnd.x - cx)
  const pointAngle = Math.atan2(mapY - cy, mapX - cx)

  // Outer arc is CCW when clockwise=false (Core annular_sector_boundary).
  if (outerArc.clockwise) {
    return angleInCounterClockwiseWedge(pointAngle, angleEnd, angleStart)
  }
  return angleInCounterClockwiseWedge(pointAngle, angleStart, angleEnd)
}

export function pointHitsMapRegionOverlay(
  mapX: number,
  mapY: number,
  overlay: MapRegionOverlay
): boolean {
  const { geometry } = overlay
  if (geometry.type === 'boundary') {
    if (pointInAnnularSectorBoundary(mapX, mapY, geometry)) return true
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
