/**
 * Planet / normal warp-well stops for fleet heading trail rays (#290).
 * Clamp trail endpoints to the planet center when a segment first intersects
 * the planet cell or its normal well (radius 3). Debris-disk bodies have no
 * well -- only the planet cell.
 */

/** Matches Core ``NORMAL_RADIUS`` for normal warp wells. */
export const FLEET_TRAIL_NORMAL_WARP_WELL_RADIUS = 3
/** Hit radius for debris-disk / planetoid cells (no extended well). */
export const FLEET_TRAIL_PLANET_CELL_RADIUS = 0.5

const HIT_EPS = 1e-9

export type FleetTrailPlanetStop = {
  x: number
  y: number
  /** Normal-well radius (3), or cell-only radius when the body has no well. */
  stopRadius: number
}

export function pointInFleetTrailPlanetStop(
  x: number,
  y: number,
  planet: FleetTrailPlanetStop
): boolean {
  return Math.hypot(planet.x - x, planet.y - y) <= planet.stopRadius + HIT_EPS
}

/** True when ``(x, y)`` lies on any planet cell or inside a normal well. */
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
 * First planet/well hit along the segment from ``(x0,y0)`` toward ``(x1,y1)``.
 * Returns the planet center (clamp target) and distance along the segment to
 * first disk entry. When ``skipPlanetsContainingStart`` is true, planets that
 * already contain the start (e.g. departing orbit) are ignored.
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
  const ux = segDx / segLen
  const uy = segDy / segLen

  let best: { x: number; y: number; distanceAlong: number } | null = null

  for (const planet of planets) {
    if (
      options.skipPlanetsContainingStart &&
      pointInFleetTrailPlanetStop(x0, y0, planet)
    ) {
      continue
    }
    const tEnter = rayDiskEntryDistance(
      x0,
      y0,
      ux,
      uy,
      planet.x,
      planet.y,
      planet.stopRadius
    )
    if (tEnter == null || tEnter > segLen + HIT_EPS) {
      continue
    }
    const distanceAlong = Math.max(0, tEnter)
    if (best == null || distanceAlong < best.distanceAlong) {
      best = { x: planet.x, y: planet.y, distanceAlong }
    }
  }

  return best
}

/**
 * Distance along unit direction ``(ux,uy)`` from ``(ox,oy)`` to first entry into
 * the disk centered at ``(cx,cy)`` with radius ``r``. Null when the ray misses
 * or only touches behind the origin.
 */
function rayDiskEntryDistance(
  ox: number,
  oy: number,
  ux: number,
  uy: number,
  cx: number,
  cy: number,
  r: number
): number | null {
  const fx = ox - cx
  const fy = oy - cy
  const distOrigin = Math.hypot(fx, fy)
  if (distOrigin <= r + HIT_EPS) {
    return 0
  }

  // Quadratic |O + t D - C|^2 = r^2 with |D|=1: t^2 + 2(F·D)t + (|F|^2 - r^2) = 0
  const b = 2 * (fx * ux + fy * uy)
  const c = fx * fx + fy * fy - r * r
  const disc = b * b - 4 * c
  if (disc < 0) {
    return null
  }
  const sqrtDisc = Math.sqrt(disc)
  const t0 = (-b - sqrtDisc) / 2
  const t1 = (-b + sqrtDisc) / 2
  const candidates = [t0, t1].filter((t) => t >= -HIT_EPS)
  if (candidates.length === 0) {
    return null
  }
  return Math.max(0, Math.min(...candidates))
}
