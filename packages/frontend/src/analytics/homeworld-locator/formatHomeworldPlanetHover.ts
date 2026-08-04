/**
 * Thin FE planet-row hover for homeworld locator candidates.
 * Composed from existing wire fields only -- no backend presentation payloads.
 */

import type { MapRegionPossibleOwner } from '../../api/mapRegionOverlayTypes'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { CONFIDENCE_DEFINITE } from './constants'
import {
  formatHomeworldOwnershipInferenceSummary,
  resolveOwnershipEvidenceForCandidate,
} from './formatHomeworldOwnershipInference'
import { formatHomeworldOwnershipPickLabel } from './ownershipPickLabel'
import type { HomeworldCandidateRecord } from './wireSchema'

function ownerSlotLabel(
  perspective: number | null,
  roster: readonly PerspectiveRow[]
): string {
  if (perspective == null) return 'orphan'
  const player = roster.find((row) => row.ordinal === perspective)
  if (player != null) {
    return formatHomeworldOwnershipPickLabel(player.name, player.raceName)
  }
  return `slot ${perspective}`
}

export type FormatHomeworldPlanetHoverOptions = {
  /** Sector (or planet-keyed) ownership evidence for expanding ``inferred``. */
  possibleOwners?: readonly MapRegionPossibleOwner[]
  /** Overlay winning ownership strength after display projection. */
  ownershipWinningStrength?: string | null
}

/** Single-line tooltip summarizing candidate location/status evidence. */
export function formatHomeworldPlanetHover(
  row: HomeworldCandidateRecord,
  roster: readonly PerspectiveRow[] = [],
  options: FormatHomeworldPlanetHoverOptions = {}
): string {
  const parts: string[] = [`planet ${row.planetId}`]

  if (row.confidenceTier === CONFIDENCE_DEFINITE) {
    parts.push('definite')
  } else if (row.isMostProbable) {
    parts.push('possible (most probable)')
  } else {
    parts.push('possible')
  }

  parts.push(`owner: ${ownerSlotLabel(row.perspective, roster)}`)

  const ownershipEvidence = resolveOwnershipEvidenceForCandidate(
    options.possibleOwners,
    row.perspective
  )
  const ownershipSummary = formatHomeworldOwnershipInferenceSummary(ownershipEvidence, {
    winningStrength: options.ownershipWinningStrength,
  })
  if (ownershipSummary != null) {
    parts.push(ownershipSummary)
  } else {
    parts.push(row.attribution)
  }

  if (row.assertedCue === true && ownershipSummary !== 'asserted') {
    parts.push('asserted')
  }

  return parts.join(' · ')
}
