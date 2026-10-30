/** On-screen analytic freshness. Words only; inference status stays beside them. */

export const TURN_LOAD_LABEL = 'Turn load'
export const PROVISIONAL_LABEL = 'Provisional'
export const PROVISIONAL_TITLE =
  'This is a saved answer from before a newer result for this player. It may change once that result is included. Backfill earlier turns updates turns you are not viewing. Otherwise a turn updates when you open it.'

export type AnalyticFreshness = 'turn-load' | 'subject-to-revision' | 'none'

/**
 * Set by stream events. Unlabeled is the gap before any admission signal.
 * Turn load is only the gap before accept when no row is stored.
 * Current has no word. Behind-mark is Provisional, including while busy.
 */
export type AnalyticFreshnessPhase = 'unlabeled' | 'turn-load' | 'current' | 'behind-mark'

export function isBehindEvidenceMark(
  evidenceGeneration: number | null | undefined,
  evidenceMark: number | null | undefined
): boolean {
  if (evidenceGeneration == null || evidenceMark == null) {
    return false
  }
  return evidenceGeneration !== evidenceMark
}

export function analyticFreshnessForPhase(phase: AnalyticFreshnessPhase): AnalyticFreshness {
  if (phase === 'turn-load') {
    return 'turn-load'
  }
  if (phase === 'behind-mark') {
    return 'subject-to-revision'
  }
  return 'none'
}

/** A stored row is current or behind the mark. It is never turn load. */
export function phaseForStoredEvidence(
  evidenceGeneration: number | null | undefined,
  evidenceMark: number | null | undefined
): 'current' | 'behind-mark' {
  return isBehindEvidenceMark(evidenceGeneration, evidenceMark) ? 'behind-mark' : 'current'
}

/** Accept ends turn load when nothing is stored. A stored row keeps its phase. */
export function freshnessPhaseAfterAccept(
  phase: AnalyticFreshnessPhase,
  hasStoredRow: boolean
): AnalyticFreshnessPhase {
  if (hasStoredRow) {
    return phase
  }
  return 'current'
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
