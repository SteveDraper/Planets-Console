/**
 * Client-side hover copy for homeworld sector region overlays.
 * Core emits structured facts only; English templates live here.
 */

import type {
  MapRegionOverlay,
  MapRegionPossibleOwner,
  OwnershipWinningStrength,
} from '../../api/mapRegionOverlayTypes'
import {
  formatHomeworldOwnershipInferenceSummary,
  uniqueOwnershipWinningStrength,
} from './formatHomeworldOwnershipInference'
import { isHomeworldSectorOverlay } from './homeworldSectorIndex'

function formatPossibleOwnerDisplay(
  owner: MapRegionPossibleOwner,
  options: {
    winningStrength: OwnershipWinningStrength | null | undefined
    allowLegacyShipDefinite?: boolean
  }
): string {
  const label =
    owner.playerLabel != null && owner.playerLabel !== ''
      ? owner.playerLabel
      : `slot ${owner.ownerSlot}`
  const inference = formatHomeworldOwnershipInferenceSummary(owner, {
    winningStrength: options.winningStrength,
    allowLegacyShipDefinite: options.allowLegacyShipDefinite,
  })
  return inference != null ? `${label} · ${inference}` : label
}

/** Single-owner hover fragment; null when pinned and inference summary is empty. */
function formatSingleOwnerLine(
  owner: MapRegionPossibleOwner,
  options: {
    includeOwnerLabels: boolean
    winningStrength: OwnershipWinningStrength | null | undefined
  }
): string | null {
  if (options.includeOwnerLabels) {
    return `homeworld owner: ${formatPossibleOwnerDisplay(owner, {
      winningStrength: options.winningStrength,
    })}`
  }
  return formatHomeworldOwnershipInferenceSummary(owner, {
    winningStrength: options.winningStrength,
  })
}

/** Ambiguous multi-owner hover fragments (status label + owners list). */
function formatAmbiguousOwners(
  possibleOwners: readonly MapRegionPossibleOwner[],
  winningStrength: OwnershipWinningStrength | null | undefined
): string[] {
  return [
    'ambiguous',
    `homeworld owners: ${possibleOwners
      .map((owner) =>
        formatPossibleOwnerDisplay(owner, {
          winningStrength,
          // Ambiguous contenders must not inherit legacy unique-owner ship→definite.
          allowLegacyShipDefinite: false,
        })
      )
      .join(', ')}`,
  ]
}

/**
 * Append ownership-evidence hover parts.
 * When ``includeOwnerLabels`` is false (pinned sectors), only the inference
 * summary is added so the determined player identity is not repeated.
 */
function appendOwnershipEvidenceParts(
  parts: string[],
  possibleOwners: readonly MapRegionPossibleOwner[],
  options: {
    includeOwnerLabels: boolean
    winningStrength?: OwnershipWinningStrength | null
  }
): void {
  if (possibleOwners.length === 0) return

  const uniqueWinningStrength = uniqueOwnershipWinningStrength(
    possibleOwners,
    options.winningStrength
  )

  if (possibleOwners.length === 1) {
    const line = formatSingleOwnerLine(possibleOwners[0]!, {
      includeOwnerLabels: options.includeOwnerLabels,
      winningStrength: uniqueWinningStrength,
    })
    if (line != null) parts.push(line)
    return
  }

  parts.push(...formatAmbiguousOwners(possibleOwners, uniqueWinningStrength))
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
