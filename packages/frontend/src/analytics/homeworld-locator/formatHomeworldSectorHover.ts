/**
 * Client-side hover copy for homeworld sector region overlays.
 * Core emits structured facts only; English templates live here.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { isHomeworldSectorOverlay } from './homeworldRegionDisplayMode'

/** Format one homeworld-sector overlay into a tooltip line, or null if not applicable. */
export function formatHomeworldSectorHoverLine(
  overlay: MapRegionOverlay
): string | null {
  if (!isHomeworldSectorOverlay(overlay)) return null
  if (overlay.status === 'error') return 'no candidates'

  const parts: string[] = []
  if (overlay.isPinned) {
    if (overlay.playerLabel != null && overlay.playerLabel !== '') {
      parts.push(`player: ${overlay.playerLabel}`)
    } else {
      parts.push('player known')
    }
  }
  if (overlay.status === 'incomplete') {
    parts.push('incomplete scan')
  }
  const count = overlay.candidateCount ?? 0
  parts.push(count === 1 ? '1 candidate homeworld' : `${count} candidate homeworlds`)
  return parts.join(' · ')
}
