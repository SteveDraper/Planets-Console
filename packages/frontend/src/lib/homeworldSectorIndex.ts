/**
 * Parse sector index from homeworld sector overlay ids (``homeworld-sector-{n}``).
 */

import type { MapRegionOverlay } from '../api/mapRegionOverlayTypes'

/** Kind emitted by Core for homeworld circular sector overlays. */
export const HOMEWORLD_SECTOR_KIND = 'homeworld-sector'

const SECTOR_ID_RE = /^homeworld-sector-(\d+)$/

/** True when the overlay is a homeworld sector entry. */
export function isHomeworldSectorOverlay(overlay: Pick<MapRegionOverlay, 'kind'>): boolean {
  return overlay.kind === HOMEWORLD_SECTOR_KIND
}

/** Extract sector index from a homeworld-sector overlay id, or null if not applicable. */
export function parseHomeworldSectorIndex(overlayId: string): number | null {
  const match = SECTOR_ID_RE.exec(overlayId)
  if (match == null) return null
  const index = Number.parseInt(match[1]!, 10)
  return Number.isFinite(index) ? index : null
}

/** True when any overlay is a homeworld sector (ownership is sector-keyed on the map). */
export function homeworldSectorsPresentOnMap(
  overlays: readonly { kind: string }[]
): boolean {
  return overlays.some((overlay) => overlay.kind === HOMEWORLD_SECTOR_KIND)
}
