/**
 * Build ``FleetTrailPlanetStop`` rows from base-map planet nodes for trail clamps.
 */

import type { MapNode } from '../../api/bff'
import { normalizeWarpWellMapCells } from '../../lib/warpWell'
import type { FleetTrailPlanetStop } from './fleetHeadingTrailPlanetStops'

/**
 * Planets that can stop a heading trail. Uses shipped ``normalWellCells`` only
 * (empty / missing ⇒ planet-cell only; no SPA well-radius geometry).
 */
export function fleetTrailPlanetStopsFromMapNodes(
  nodes: readonly Pick<MapNode, 'x' | 'y' | 'planet' | 'normalWellCells'>[]
): FleetTrailPlanetStop[] {
  const out: FleetTrailPlanetStop[] = []
  for (const node of nodes) {
    if (node.planet == null) {
      continue
    }
    out.push({
      x: node.x,
      y: node.y,
      wellCells: normalizeWarpWellMapCells(node.normalWellCells),
    })
  }
  return out
}
