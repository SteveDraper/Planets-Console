/**
 * Client-side hover copy for homeworld sector region overlays.
 * Core emits structured facts only; English templates live here.
 */

import type {
  MapRegionOverlay,
  MapRegionPossibleOwner,
} from '../../api/mapRegionOverlayTypes'
import { isHomeworldSectorOverlay } from './homeworldRegionDisplayMode'

function formatPossibleOwnerDisplay(owner: MapRegionPossibleOwner): string {
  if (owner.playerLabel != null && owner.playerLabel !== '') {
    return owner.playerLabel
  }
  return `slot ${owner.ownerSlot}`
}

/** Format one homeworld-sector overlay into a tooltip line, or null if not applicable. */
export function formatHomeworldSectorHoverLine(
  overlay: MapRegionOverlay
): string | null {
  if (!isHomeworldSectorOverlay(overlay)) return null
  if (overlay.status === 'error') return 'no candidates'

  const parts: string[] = []
  const possibleOwners = overlay.possibleOwners ?? []

  // Pinned sectors keep the determined-HW identity; ownership evidence is for
  // unpinned sectors (avoid duplicating owner text when both are present).
  if (overlay.isPinned) {
    if (overlay.playerLabel != null && overlay.playerLabel !== '') {
      parts.push(`player: ${overlay.playerLabel}`)
    } else {
      parts.push('player known')
    }
  } else if (possibleOwners.length === 1) {
    parts.push(`homeworld owner: ${formatPossibleOwnerDisplay(possibleOwners[0])}`)
  } else if (possibleOwners.length > 1) {
    parts.push('ambiguous')
    parts.push(
      `homeworld owners: ${possibleOwners.map(formatPossibleOwnerDisplay).join(', ')}`
    )
  }

  if (overlay.status === 'incomplete') {
    parts.push('incomplete scan')
  }
  const count = overlay.candidateCount ?? 0
  parts.push(count === 1 ? '1 candidate homeworld' : `${count} candidate homeworlds`)
  return parts.join(' · ')
}
