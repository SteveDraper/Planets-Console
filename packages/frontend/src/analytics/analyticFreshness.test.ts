import { describe, expect, it } from 'vitest'
import {
  PROVISIONAL_LABEL,
  PROVISIONAL_TITLE,
  TURN_LOAD_LABEL,
  analyticFreshnessClassName,
  analyticFreshnessForPhase,
  analyticFreshnessLabel,
  analyticFreshnessTitle,
  freshnessPhaseAfterAccept,
  isBehindEvidenceMark,
  phaseForStoredEvidence,
} from './analyticFreshness'

describe('analytic freshness phase', () => {
  it('shows no word before any admission signal and after accept with nothing stored', () => {
    expect(analyticFreshnessForPhase('unlabeled')).toBe('none')
    expect(analyticFreshnessForPhase('current')).toBe('none')
    expect(freshnessPhaseAfterAccept('turn-load', false)).toBe('current')
    expect(freshnessPhaseAfterAccept('unlabeled', false)).toBe('current')
  })

  it('shows turn load only from the turn-load phase', () => {
    expect(analyticFreshnessForPhase('turn-load')).toBe('turn-load')
  })

  it('maps a stored row to current or behind-mark, never turn load', () => {
    expect(phaseForStoredEvidence(3, 3)).toBe('current')
    expect(phaseForStoredEvidence(1, 2)).toBe('behind-mark')
    expect(phaseForStoredEvidence(null, 2)).toBe('current')
    expect(analyticFreshnessForPhase('behind-mark')).toBe('subject-to-revision')
    expect(freshnessPhaseAfterAccept('behind-mark', true)).toBe('behind-mark')
    expect(isBehindEvidenceMark(3, 3)).toBe(false)
    expect(isBehindEvidenceMark(1, 2)).toBe(true)
  })
})

describe('analytic freshness copy', () => {
  it('uses slate for turn load and amber for provisional', () => {
    expect(analyticFreshnessLabel('turn-load')).toBe(TURN_LOAD_LABEL)
    expect(analyticFreshnessLabel('subject-to-revision')).toBe(PROVISIONAL_LABEL)
    expect(analyticFreshnessLabel('none')).toBeNull()
    expect(analyticFreshnessTitle('subject-to-revision')).toBe(PROVISIONAL_TITLE)
    expect(analyticFreshnessTitle('turn-load')).toBeNull()
    expect(analyticFreshnessClassName('turn-load')).toBe('text-slate-400')
    expect(analyticFreshnessClassName('subject-to-revision')).toBe('text-amber-300')
  })
})
