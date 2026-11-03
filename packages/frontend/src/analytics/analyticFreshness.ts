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

/** Evidence carried on a paint event. Absent fields keep the previous value. */
export type FreshnessEvidenceEvent = {
  evidenceGeneration?: number | null
  evidenceMark?: number | null
}

export type FreshnessState = {
  phase: AnalyticFreshnessPhase
  hasStoredRow: boolean
  evidenceGeneration: number | null
  evidenceMark: number | null
}

export function initialFreshnessState(): FreshnessState {
  return {
    phase: 'unlabeled',
    hasStoredRow: false,
    evidenceGeneration: null,
    evidenceMark: null,
  }
}

function evidenceFrom(
  state: FreshnessState,
  event: FreshnessEvidenceEvent
): Pick<FreshnessState, 'evidenceGeneration' | 'evidenceMark'> {
  return {
    evidenceGeneration:
      event.evidenceGeneration != null ? event.evidenceGeneration : state.evidenceGeneration,
    evidenceMark: event.evidenceMark != null ? event.evidenceMark : state.evidenceMark,
  }
}

function withPhase(state: FreshnessState, phase: AnalyticFreshnessPhase): FreshnessState {
  if (state.phase === phase) {
    return state
  }
  return { ...state, phase }
}

function phaseForStoredEvidence(
  evidenceGeneration: number | null,
  evidenceMark: number | null
): 'current' | 'behind-mark' {
  if (evidenceGeneration == null || evidenceMark == null) {
    return 'current'
  }
  return evidenceGeneration === evidenceMark ? 'current' : 'behind-mark'
}

/**
 * Evidence from a paint that is not a stored row.
 * Phase is left for the absent or current paint that follows.
 */
function freshnessClearingStoredRow(
  state: FreshnessState,
  event: FreshnessEvidenceEvent
): FreshnessState {
  return {
    phase: state.phase,
    hasStoredRow: false,
    ...evidenceFrom(state, event),
  }
}

/**
 * An absent admission signal is turn load only before accept.
 * Current and behind-mark stay: accept already happened, or a stored row is showing.
 */
export function freshnessAfterAbsent(state: FreshnessState): FreshnessState {
  if (state.phase === 'current' || state.phase === 'behind-mark') {
    return state
  }
  return withPhase(state, 'turn-load')
}

/**
 * A paint that is not a stored row. Evidence updates when the event carries it.
 * Phase follows the absent-signal rule, so a provisional row stays provisional.
 */
export function freshnessAfterAbsentPaint(
  state: FreshnessState,
  event: FreshnessEvidenceEvent
): FreshnessState {
  return freshnessAfterAbsent(freshnessClearingStoredRow(state, event))
}

/**
 * A stored row is current or behind the mark.
 * Evidence fields update when the event carries them.
 */
export function freshnessAfterStoredPaint(
  state: FreshnessState,
  event: FreshnessEvidenceEvent
): FreshnessState {
  const evidence = evidenceFrom(state, event)
  return {
    phase: phaseForStoredEvidence(evidence.evidenceGeneration, evidence.evidenceMark),
    hasStoredRow: true,
    ...evidence,
  }
}

/**
 * A painted result that is not a stored row is current.
 * Evidence updates when the event carries it.
 */
export function freshnessAfterCurrentPaint(
  state: FreshnessState,
  event: FreshnessEvidenceEvent
): FreshnessState {
  return withPhase(freshnessClearingStoredRow(state, event), 'current')
}

/** Accept ends turn load when nothing is stored. A stored row keeps its phase. */
export function freshnessAfterAccept(state: FreshnessState): FreshnessState {
  if (state.hasStoredRow) {
    return state
  }
  return withPhase(state, 'current')
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
