/**
 * Build planetId → ownership assert target from sector overlays + planet coords.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  resolveOwnershipAssertTargetForPlanet,
  type OwnershipAssertTarget,
} from './resolveOwnershipAssertTarget'
import { homeworldSectorsPresentOnMap } from './homeworldSectorIndex'

export function buildPlanetOwnershipTargets(
  overlays: readonly MapRegionOverlay[],
  planetPositions: ReadonlyMap<number, { x: number; y: number }>
): Map<number, OwnershipAssertTarget> {
  const out = new Map<number, OwnershipAssertTarget>()
  const sectorsPresent = homeworldSectorsPresentOnMap(overlays)
  for (const [planetId, pos] of planetPositions) {
    if (!sectorsPresent) {
      out.set(planetId, { keying: 'planet', planetId })
      continue
    }
    const target = resolveOwnershipAssertTargetForPlanet(
      overlays,
      planetId,
      pos.x,
      pos.y
    )
    if (target != null) {
      out.set(planetId, target)
    }
  }
  return out
}
