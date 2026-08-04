/**
 * Resolve which homeworld sector should paint as selected from UI selection.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import type { HomeworldLocatorSelection } from '../../stores/homeworldLocatorSelection'
import { parseHomeworldSectorIndex } from './homeworldSectorIndex'
import { findHomeworldSectorAtMapPoint } from './resolveOwnershipAssertTarget'

export type HomeworldSelectedSectorMarker = {
  planetId: number
  x: number
  y: number
}

/**
 * Sector index for region paint highlight from panel/table/map selection.
 * Sector selection uses ``sectorIndex`` directly; planet selection hit-tests
 * the selected planet's marker against filtered sector overlays.
 */
export function resolveHomeworldSelectedSectorIndex(
  selection: HomeworldLocatorSelection,
  markers: readonly HomeworldSelectedSectorMarker[],
  overlays: readonly MapRegionOverlay[]
): number | null {
  if (selection?.kind === 'sector') {
    return selection.sectorIndex
  }
  if (selection?.kind === 'planet') {
    const marker = markers.find((m) => m.planetId === selection.planetId)
    if (marker == null) return null
    const planetOverlay = findHomeworldSectorAtMapPoint(overlays, marker.x, marker.y)
    if (planetOverlay == null) return null
    return parseHomeworldSectorIndex(planetOverlay.id)
  }
  return null
}
