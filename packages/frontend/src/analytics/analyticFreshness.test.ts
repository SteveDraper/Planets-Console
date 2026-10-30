import { describe, expect, it } from 'vitest'
import {
  PROVISIONAL_LABEL,
  PROVISIONAL_TITLE,
  TURN_LOAD_LABEL,
  analyticFreshnessClassName,
  analyticFreshnessLabel,
  analyticFreshnessTitle,
  isBehindEvidenceMark,
  resolveAnalyticFreshness,
} from './analyticFreshness'

describe('resolveAnalyticFreshness', () => {
  it('shows turn load only before accept when nothing is stored', () => {
    expect(
      resolveAnalyticFreshness({
        hasStoredRow: false,
        workAccepted: false,
        behindEvidenceMark: false,
      })
    ).toBe('turn-load')
  })

  it('drops freshness words after accept when the first compute has no stored row', () => {
    expect(
      resolveAnalyticFreshness({
        hasStoredRow: false,
        workAccepted: true,
        behindEvidenceMark: false,
      })
    ).toBe('none')
  })

  it('never shows turn load for a stored row', () => {
    expect(
      resolveAnalyticFreshness({
        hasStoredRow: true,
        workAccepted: false,
        behindEvidenceMark: false,
      })
    ).toBe('none')
    expect(
      resolveAnalyticFreshness({
        hasStoredRow: true,
        workAccepted: false,
        behindEvidenceMark: true,
      })
    ).toBe('subject-to-revision')
  })

  it('keeps subject to revision while a recompute is accepted', () => {
    expect(
      resolveAnalyticFreshness({
        hasStoredRow: true,
        workAccepted: true,
        behindEvidenceMark: true,
      })
    ).toBe('subject-to-revision')
  })

  it('treats a matching generation as complete, including an approximate fleet', () => {
    expect(isBehindEvidenceMark(3, 3)).toBe(false)
    expect(
      resolveAnalyticFreshness({
        hasStoredRow: true,
        workAccepted: true,
        behindEvidenceMark: isBehindEvidenceMark(3, 3),
      })
    ).toBe('none')
  })

  it('treats a skip with no stored row as complete', () => {
    expect(
      resolveAnalyticFreshness({
        hasStoredRow: false,
        workAccepted: false,
        behindEvidenceMark: false,
        skippedWithoutStoredRow: true,
      })
    ).toBe('none')
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
