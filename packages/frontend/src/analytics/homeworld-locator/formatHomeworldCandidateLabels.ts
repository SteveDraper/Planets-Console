/**
 * Shared homeworld candidate confidence and owner-slot display labels.
 * Table UI uses Title Case; planet hover uses lowercase.
 */

import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { CONFIDENCE_DEFINITE } from './constants'
import { formatHomeworldOwnershipPickLabel } from './ownershipPickLabel'
import type { HomeworldCandidateRecord } from './wireSchema'

export type HomeworldCandidateLabelCasing = 'title' | 'lower'

export type FormatHomeworldCandidateConfidenceLabelOptions = {
  casing?: HomeworldCandidateLabelCasing
  /** When true, fold assertedCue into the label (table UI). Hover keeps asserted separate. */
  includeAsserted?: boolean
}

type CandidateConfidenceFields = Pick<
  HomeworldCandidateRecord,
  'confidenceTier' | 'isMostProbable' | 'assertedCue'
>

const CONFIDENCE_LABELS = {
  definite: { title: 'Definite', lower: 'definite' },
  possible: { title: 'Possible', lower: 'possible' },
  possibleMostProbable: {
    title: 'Possible (most probable)',
    lower: 'possible (most probable)',
  },
  possibleMostProbableAsserted: {
    title: 'Possible (most probable, asserted)',
    lower: 'possible (most probable, asserted)',
  },
} as const

/** Base confidence tier label for a homeworld candidate row. */
export function formatHomeworldCandidateConfidenceLabel(
  row: CandidateConfidenceFields,
  options: FormatHomeworldCandidateConfidenceLabelOptions = {}
): string {
  const casing = options.casing ?? 'title'
  const includeAsserted = options.includeAsserted ?? false

  let label: string
  if (row.confidenceTier === CONFIDENCE_DEFINITE) {
    label = CONFIDENCE_LABELS.definite[casing]
  } else if (row.isMostProbable) {
    label = CONFIDENCE_LABELS.possibleMostProbable[casing]
  } else {
    label = CONFIDENCE_LABELS.possible[casing]
  }

  if (includeAsserted && row.assertedCue === true) {
    if (row.isMostProbable && row.confidenceTier !== CONFIDENCE_DEFINITE) {
      return CONFIDENCE_LABELS.possibleMostProbableAsserted[casing]
    }
    return `${label} (asserted)`
  }

  return label
}

export type FormatHomeworldCandidateOwnerSlotLabelOptions = {
  casing?: HomeworldCandidateLabelCasing
}

/** Owner column / hover owner slot label for a homeworld candidate. */
export function formatHomeworldCandidateOwnerSlotLabel(
  perspective: number | null,
  roster: readonly PerspectiveRow[],
  options: FormatHomeworldCandidateOwnerSlotLabelOptions = {}
): string {
  const casing = options.casing ?? 'title'

  if (perspective == null) {
    return casing === 'title' ? 'Orphan' : 'orphan'
  }

  const player = roster.find((row) => row.ordinal === perspective)
  if (player != null) {
    return formatHomeworldOwnershipPickLabel(player.name, player.raceName)
  }

  const slotWord = casing === 'title' ? 'Slot' : 'slot'
  return `${slotWord} ${perspective}`
}
