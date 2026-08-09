/**
 * Planet / normal warp-well stops for fleet heading trail rays (#290).
 * Well membership uses server ``normalWellCells`` (and the planet map cell);
 * there is no SPA twin of Core ``NORMAL_RADIUS`` continuous geometry.
 *
 * Stops fire on exact planet coordinates along a segment, or when a segment
 * endpoint lands in the planet cell / well cells -- not mid-path continuous
 * disk entry.
 */

import type { WarpWellMapCell } from '../../lib/warpWell'

const HIT_EPS = 1e-9

export type FleetTrailPlanetStop = {
  x: number
  y: number
  /**
   * Server ``normalWellCells`` (normalized). Empty ⇒ debris / planet-cell only
   * (no extended well).
   */
  wellCells: readonly WarpWellMapCell[]
}

/** Map cell index for a continuous point (matches Core debris reachability rounding). */
export function fleetTrailMapCellIndex(x: number, y: number): WarpWellMapCell {
  return { x: Math.round(x), y: Math.round(y) }
}

export function pointInFleetTrailPlanetStop(
  x: number,
  y: number,
  planet: FleetTrailPlanetStop
): boolean {
  if (Math.abs(x - planet.x) <= HIT_EPS && Math.abs(y - planet.y) <= HIT_EPS) {
    return true
  }
  const cell = fleetTrailMapCellIndex(x, y)
  if (planet.wellCells.length === 0) {
    return cell.x === planet.x && cell.y === planet.y
  }
  for (const wellCell of planet.wellCells) {
    if (wellCell.x === cell.x && wellCell.y === cell.y) {
      return true
    }
  }
  return false
}

/** True when ``(x, y)`` lies on any planet cell or inside a shipped normal well. */
export function pointInAnyFleetTrailPlanetStop(
  x: number,
  y: number,
  planets: readonly FleetTrailPlanetStop[]
): boolean {
  for (const planet of planets) {
    if (pointInFleetTrailPlanetStop(x, y, planet)) {
      return true
    }
  }
  return false
}

/**
 * First planet/well stop along the segment from ``(x0,y0)`` toward ``(x1,y1)``.
 * Hits when the ray passes through exact planet coordinates, or when the
 * segment endpoint lies in that planet's cell / well cells. Returns the planet
 * center (clamp target) and distance along the segment used for ordering.
 * When ``skipPlanetsContainingStart`` is true, planets that already contain the
 * start (e.g. departing orbit) are ignored.
 */
export function firstFleetTrailPlanetStopAlongSegment(
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  planets: readonly FleetTrailPlanetStop[],
  options: { skipPlanetsContainingStart: boolean } = {
    skipPlanetsContainingStart: false,
  }
): { x: number; y: number; distanceAlong: number } | null {
  const segDx = x1 - x0
  const segDy = y1 - y0
  const segLen = Math.hypot(segDx, segDy)
  if (segLen <= HIT_EPS || planets.length === 0) {
    return null
  }

  let best: { x: number; y: number; distanceAlong: number } | null = null

  for (const planet of planets) {
    if (
      options.skipPlanetsContainingStart &&
      pointInFleetTrailPlanetStop(x0, y0, planet)
    ) {
      continue
    }

    const exactAlong = exactPlanetDistanceAlongSegment(
      x0,
      y0,
      segDx,
      segDy,
      segLen,
      planet.x,
      planet.y
    )
    const endInStop = pointInFleetTrailPlanetStop(x1, y1, planet)
    if (exactAlong == null && !endInStop) {
      continue
    }

    // Exact planet: along-ray distance to the planet. End-in-well only: full
    // segment length to the projected endpoint (not planet-center hypot).
    // When both apply, exactAlong ≤ segLen so the nearer event wins.
    const distanceAlong = exactAlong ?? segLen

    if (best == null || distanceAlong < best.distanceAlong) {
      best = { x: planet.x, y: planet.y, distanceAlong }
    }
  }

  return best
}

/**
 * Distance along the segment to exact planet ``(px,py)`` when that point lies on
 * the segment; otherwise null.
 */
function exactPlanetDistanceAlongSegment(
  x0: number,
  y0: number,
  segDx: number,
  segDy: number,
  segLen: number,
  px: number,
  py: number
): number | null {
  const toPx = px - x0
  const toPy = py - y0
  const cross = segDx * toPy - segDy * toPx
  if (Math.abs(cross) > HIT_EPS * segLen) {
    return null
  }
  const along = (toPx * segDx + toPy * segDy) / segLen
  if (along < -HIT_EPS || along > segLen + HIT_EPS) {
    return null
  }
  return Math.max(0, Math.min(along, segLen))
}
