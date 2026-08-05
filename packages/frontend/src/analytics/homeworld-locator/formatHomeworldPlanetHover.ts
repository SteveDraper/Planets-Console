/**
 * Thin FE planet-row hover for homeworld locator candidates.
 * Composed from existing wire fields only -- no backend presentation payloads.
 */

import type {
  MapRegionPossibleOwner,
  OwnershipWinningStrength,
} from '../../api/mapRegionOverlayTypes'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import {
  formatHomeworldCandidateConfidenceLabel,
  formatHomeworldCandidateOwnerSlotLabel,
} from './formatHomeworldCandidateLabels'
import {
  formatHomeworldOwnershipInferenceSummary,
  resolveOwnershipEvidenceForCandidate,
  uniqueOwnershipWinningStrength,
} from './formatHomeworldOwnershipInference'
import type { HomeworldCandidateRecord } from './wireSchema'

export type FormatHomeworldPlanetHoverOptions = {
  /** Sector (or planet-keyed) ownership evidence for expanding ``inferred``. */
  possibleOwners?: readonly MapRegionPossibleOwner[]
  /** Overlay winning ownership strength after overlay projection. */
  ownershipWinningStrength?: OwnershipWinningStrength | null
}

/** Single-line tooltip summarizing candidate location/status evidence. */
export function formatHomeworldPlanetHover(
  row: HomeworldCandidateRecord,
  roster: readonly PerspectiveRow[] = [],
  options: FormatHomeworldPlanetHoverOptions = {}
): string {
  const parts: string[] = [`planet ${row.planetId}`]

  parts.push(
    formatHomeworldCandidateConfidenceLabel(row, { casing: 'lower' })
  )

  parts.push(
    `owner: ${formatHomeworldCandidateOwnerSlotLabel(row.perspective, roster, { casing: 'lower' })}`
  )

  const ownershipEvidence = resolveOwnershipEvidenceForCandidate(
    options.possibleOwners,
    row.perspective
  )
  const ownershipSummary = formatHomeworldOwnershipInferenceSummary(ownershipEvidence, {
    winningStrength: uniqueOwnershipWinningStrength(
      options.possibleOwners,
      options.ownershipWinningStrength
    ),
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
