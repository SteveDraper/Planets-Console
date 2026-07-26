/**
 * Kind-dispatch for region-overlay hover lines (UI copy lives with analytics).
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { formatHomeworldSectorHoverLine } from '../../analytics/homeworld-locator/formatHomeworldSectorHover'

/** Format a hit overlay into a tooltip line, or null when the kind has no hover. */
export function formatRegionOverlayHoverLine(
  overlay: MapRegionOverlay
): string | null {
  return formatHomeworldSectorHoverLine(overlay)
}
