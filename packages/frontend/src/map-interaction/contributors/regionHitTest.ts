/**
 * Region overlay descriptive hit-test for the **map interaction surface**.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { regionOverlayHoverLinesAtClient } from '../../components/map-graph/RegionOverlayHoverPanel'
import type { MapHitContext } from '../mapInteractionContributorTypes'

export function hitTestRegionLinesAtPointer(
  hit: MapHitContext,
  regionOverlays: readonly MapRegionOverlay[]
): string[] {
  if (regionOverlays.length === 0) return []
  return regionOverlayHoverLinesAtClient(
    regionOverlays,
    hit.clientPos.x,
    hit.clientPos.y,
    hit.domNode,
    hit.transform
  )
}
