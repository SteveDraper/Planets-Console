import { mapLyToSampleCell } from '../planetSpatialGrid'

/** Host-aligned star cluster halo radiation at a map cell (matches Core sample_at). */

export type StarClusterRadiationBody = {
  x: number
  y: number
  radius: number
  temp: number
  mass: number
}

export function starClusterHaloRadiusLy(mass: number): number {
  if (!Number.isFinite(mass) || mass <= 0) return 0
  return Math.sqrt(mass)
}

export function starClusterRadiationAt(
  mapCellX: number,
  mapCellY: number,
  body: StarClusterRadiationBody
): number {
  const dist = Math.hypot(mapCellX - body.x, mapCellY - body.y)
  if (dist <= body.radius) return 0
  const halo = starClusterHaloRadiusLy(body.mass)
  if (dist >= halo) return 0
  return Math.ceil((body.temp / 100) * (1 - dist / halo))
}

export function starClusterRadiationSumAt(
  mapCellX: number,
  mapCellY: number,
  bodies: readonly StarClusterRadiationBody[]
): number {
  let total = 0
  for (const body of bodies) {
    total += starClusterRadiationAt(mapCellX, mapCellY, body)
  }
  return total
}

/** Continuous falloff for iso-contour boundaries (matches host formula without CEIL). */
export function starClusterRadiationContinuousAt(
  mapX: number,
  mapY: number,
  body: StarClusterRadiationBody
): number {
  const dist = Math.hypot(mapX - body.x, mapY - body.y)
  if (dist <= body.radius) return 0
  const halo = starClusterHaloRadiusLy(body.mass)
  if (dist >= halo) return 0
  return (body.temp / 100) * (1 - dist / halo)
}

export function starClusterRadiationContinuousSumAt(
  mapX: number,
  mapY: number,
  bodies: readonly StarClusterRadiationBody[]
): number {
  let total = 0
  for (const body of bodies) {
    total += starClusterRadiationContinuousAt(mapX, mapY, body)
  }
  return total
}

/** Host sampled flux at the map ly cell under ``(mapX, mapY)`` (matches hover + Core sample_at). */
export function starClusterRadiationHostSumAt(
  mapX: number,
  mapY: number,
  bodies: readonly StarClusterRadiationBody[]
): number {
  const { cellX, cellY } = mapLyToSampleCell(mapX, mapY)
  return starClusterRadiationSumAt(cellX, cellY, bodies)
}

/** Iso-contour threshold for host-aligned boundaries (integer flux > 0). */
export const STAR_CLUSTER_RADIATION_BOUNDARY_THRESHOLD = 0.5

export function starClusterIsLethalAt(
  mapCellX: number,
  mapCellY: number,
  body: StarClusterRadiationBody
): boolean {
  return Math.hypot(mapCellX - body.x, mapCellY - body.y) <= body.radius
}
