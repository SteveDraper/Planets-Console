/**
 * Build ``FleetTrailPlanetStop`` rows from base-map planet nodes for trail clamps.
 */

import type { MapNode } from '../../api/bff'
import {
  FLEET_TRAIL_NORMAL_WARP_WELL_RADIUS,
  FLEET_TRAIL_PLANET_CELL_RADIUS,
  type FleetTrailPlanetStop,
} from './fleetHeadingTrailPlanetStops'

/**
 * Planets that can stop a heading trail. Prefer ``normalWellCells`` when present
 * (empty ⇒ debris / no well); otherwise treat missing debrisdisk as a normal well.
 */
export function fleetTrailPlanetStopsFromMapNodes(
  nodes: readonly Pick<MapNode, 'x' | 'y' | 'planet' | 'normalWellCells'>[]
): FleetTrailPlanetStop[] {
  const out: FleetTrailPlanetStop[] = []
  for (const node of nodes) {
    if (node.planet == null) {
      continue
    }
    const hasWell =
      node.normalWellCells != null
        ? node.normalWellCells.length > 0
        : !isDebrisDiskBody(node.planet.debrisdisk)
    out.push({
      x: node.x,
      y: node.y,
      stopRadius: hasWell
        ? FLEET_TRAIL_NORMAL_WARP_WELL_RADIUS
        : FLEET_TRAIL_PLANET_CELL_RADIUS,
    })
  }
  return out
}

function isDebrisDiskBody(debrisdisk: unknown): boolean {
  if (typeof debrisdisk === 'number' && Number.isFinite(debrisdisk)) {
    return debrisdisk !== 0
  }
  if (typeof debrisdisk === 'string' && debrisdisk.trim() !== '') {
    const parsed = Number(debrisdisk)
    return Number.isFinite(parsed) && parsed !== 0
  }
  return false
}
