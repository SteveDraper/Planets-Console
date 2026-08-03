/**
 * Resolve ownership assert keying for map/panel targets.
 * Sector-keyed when homeworld sector overlays are present; else planet-keyed.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { pointHitsMapRegionOverlay } from '../../lib/mapRegionOverlayHitTest'
import { isHomeworldSectorOverlay } from './homeworldRegionDisplayMode'
import {
  homeworldSectorsPresentOnMap,
  parseHomeworldSectorIndex,
} from './homeworldSectorIndex'

export type OwnershipAssertTarget =
  | { keying: 'sector'; sectorIndex: number; planetId?: number }
  | { keying: 'planet'; planetId: number }

/** Find the homeworld sector overlay containing map coordinates, if any. */
export function findHomeworldSectorAtMapPoint(
  overlays: readonly MapRegionOverlay[],
  mapX: number,
  mapY: number
): MapRegionOverlay | null {
  for (const overlay of overlays) {
    if (!isHomeworldSectorOverlay(overlay)) continue
    if (pointHitsMapRegionOverlay(mapX, mapY, overlay)) {
      return overlay
    }
  }
  return null
}

/**
 * Ownership target for a planet at ``(mapX, mapY)``.
 * When sectors are on the map, resolves the containing sector; otherwise planet-keyed.
 */
export function resolveOwnershipAssertTargetForPlanet(
  overlays: readonly MapRegionOverlay[],
  planetId: number,
  mapX: number,
  mapY: number
): OwnershipAssertTarget | null {
  if (!homeworldSectorsPresentOnMap(overlays)) {
    return { keying: 'planet', planetId }
  }
  const sector = findHomeworldSectorAtMapPoint(overlays, mapX, mapY)
  if (sector == null) return null
  const sectorIndex = parseHomeworldSectorIndex(sector.id)
  if (sectorIndex == null) return null
  return { keying: 'sector', sectorIndex, planetId }
}

/** Ownership target for a sector overlay context menu. */
export function resolveOwnershipAssertTargetForSector(
  overlay: MapRegionOverlay
): OwnershipAssertTarget | null {
  if (!isHomeworldSectorOverlay(overlay)) return null
  const sectorIndex = parseHomeworldSectorIndex(overlay.id)
  if (sectorIndex == null) return null
  return { keying: 'sector', sectorIndex }
}
