/**
 * Client-side hover copy for homeworld sector region overlays.
 * Core emits structured facts only; English templates live here.
 */

import type {
  MapRegionOverlay,
  MapRegionPossibleOwner,
} from '../../api/mapRegionOverlayTypes'
import { formatHomeworldOwnershipInferenceSummary } from './formatHomeworldOwnershipInference'
import { isHomeworldSectorOverlay } from './homeworldSectorIndex'

function formatPossibleOwnerDisplay(
  owner: MapRegionPossibleOwner,
  winningStrength: string | null | undefined
): string {
  const label =
    owner.playerLabel != null && owner.playerLabel !== ''
      ? owner.playerLabel
      : `slot ${owner.ownerSlot}`
  const inference = formatHomeworldOwnershipInferenceSummary(owner, {
    winningStrength,
  })
  return inference != null ? `${label} · ${inference}` : label
}

/**
 * Append ownership-evidence hover parts.
 * When ``includeOwnerLabels`` is false (pinned sectors), only the inference
 * summary is added so the determined player identity is not repeated.
 */
function appendOwnershipEvidenceParts(
  parts: string[],
  possibleOwners: readonly MapRegionPossibleOwner[],
  options: { includeOwnerLabels: boolean; winningStrength?: string | null }
): void {
  if (possibleOwners.length === 0) return

  // Sector winning strength labels apply only when ``|set|=1`` (design §4.3.2).
  // Ambiguous contenders use each member's kinds/counts, never the sector max.
  const uniqueWinningStrength =
    possibleOwners.length === 1 ? options.winningStrength : undefined

  if (!options.includeOwnerLabels) {
    if (possibleOwners.length === 1) {
      const summary = formatHomeworldOwnershipInferenceSummary(possibleOwners[0]!, {
        winningStrength: uniqueWinningStrength,
      })
      if (summary != null) parts.push(summary)
      return
    }
    parts.push('ambiguous')
    parts.push(
      `homeworld owners: ${possibleOwners
        .map((owner) => formatPossibleOwnerDisplay(owner, uniqueWinningStrength))
        .join(', ')}`
    )
    return
  }

  if (possibleOwners.length === 1) {
    parts.push(
      `homeworld owner: ${formatPossibleOwnerDisplay(
        possibleOwners[0]!,
        uniqueWinningStrength
      )}`
    )
    return
  }
  parts.push('ambiguous')
  parts.push(
    `homeworld owners: ${possibleOwners
      .map((owner) => formatPossibleOwnerDisplay(owner, uniqueWinningStrength))
      .join(', ')}`
  )
}

/** Format one homeworld-sector overlay into a tooltip line, or null if not applicable. */
export function formatHomeworldSectorHoverLine(
  overlay: MapRegionOverlay
): string | null {
  if (!isHomeworldSectorOverlay(overlay)) return null
  if (overlay.status === 'error') return 'no candidates'

  const parts: string[] = []
  const possibleOwners = overlay.possibleOwners ?? []
  const winningStrength = overlay.ownershipWinningStrength

  // Pinned: determined-HW player identity first; still surface ownership
  // observation counts from possibleOwners without repeating the owner label.
  if (overlay.isPinned) {
    if (overlay.playerLabel != null && overlay.playerLabel !== '') {
      parts.push(`player: ${overlay.playerLabel}`)
    } else {
      parts.push('player known')
    }
    if (possibleOwners.length === 0) {
      parts.push('definite')
    } else {
      appendOwnershipEvidenceParts(parts, possibleOwners, {
        includeOwnerLabels: false,
        winningStrength,
      })
    }
  } else {
    appendOwnershipEvidenceParts(parts, possibleOwners, {
      includeOwnerLabels: true,
      winningStrength,
    })
  }

  if (overlay.status === 'incomplete') {
    parts.push('incomplete scan')
  }
  const count = overlay.candidateCount ?? 0
  parts.push(count === 1 ? '1 candidate homeworld' : `${count} candidate homeworlds`)
  return parts.join(' · ')
}
