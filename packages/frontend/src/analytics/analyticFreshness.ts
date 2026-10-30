/** On-screen analytic freshness. Words only; inference status stays beside them. */

export const TURN_LOAD_LABEL = 'Turn load'
export const PROVISIONAL_LABEL = 'Provisional'
export const PROVISIONAL_TITLE =
  'Some prior fleet information is missing. Turning on Backfill earlier turns would allow a more exact inference.'

export type AnalyticFreshness = 'turn-load' | 'subject-to-revision' | 'none'

export function isBehindEvidenceMark(
  evidenceGeneration: number | null | undefined,
  evidenceMark: number | null | undefined
): boolean {
  if (evidenceGeneration == null || evidenceMark == null) {
    return false
  }
  return evidenceGeneration !== evidenceMark
}

/**
 * Turn load is only the gap before accept when no row is stored.
 * A stored row behind the mark is subject to revision, including an idle row.
 * A matching generation is complete, including an approximate fleet on that mark.
 * A skip with no stored row is complete.
 */
export function resolveAnalyticFreshness(input: {
  hasStoredRow: boolean
  workAccepted: boolean
  behindEvidenceMark: boolean
  skippedWithoutStoredRow?: boolean
}): AnalyticFreshness {
  if (input.skippedWithoutStoredRow) {
    return 'none'
  }
  if (!input.hasStoredRow) {
    return input.workAccepted ? 'none' : 'turn-load'
  }
  if (input.behindEvidenceMark) {
    return 'subject-to-revision'
  }
  return 'none'
}

export function analyticFreshnessLabel(freshness: AnalyticFreshness): string | null {
  if (freshness === 'turn-load') {
    return TURN_LOAD_LABEL
  }
  if (freshness === 'subject-to-revision') {
    return PROVISIONAL_LABEL
  }
  return null
}

/** Hover explanation for a freshness label. Turn load has none. */
export function analyticFreshnessTitle(freshness: AnalyticFreshness): string | null {
  if (freshness === 'subject-to-revision') {
    return PROVISIONAL_TITLE
  }
  return null
}

/** Slate for turn load; amber in the same family as the fleet count-discrepancy line. */
export function analyticFreshnessClassName(freshness: AnalyticFreshness): string | null {
  if (freshness === 'turn-load') {
    return 'text-slate-400'
  }
  if (freshness === 'subject-to-revision') {
    return 'text-amber-300'
  }
  return null
}
