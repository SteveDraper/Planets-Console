import { describe, expect, it } from 'vitest'
import {
  analyticFreshnessForPhase,
  freshnessAfterAbsent,
  freshnessAfterAbsentPaint,
  freshnessAfterAccept,
  freshnessAfterCurrentPaint,
  freshnessAfterStoredPaint,
  initialFreshnessState,
} from './analyticFreshness'

describe('analytic freshness phase', () => {
  it('shows no word before any admission signal and after accept with nothing stored', () => {
    const initial = initialFreshnessState()
    expect(analyticFreshnessForPhase(initial.phase)).toBe('none')
    const accepted = freshnessAfterAccept(freshnessAfterAbsent(initial))
    expect(accepted.phase).toBe('current')
    expect(analyticFreshnessForPhase(accepted.phase)).toBe('none')
    expect(freshnessAfterAccept(initial).phase).toBe('current')
  })

  it('shows turn load only from the turn-load phase', () => {
    expect(analyticFreshnessForPhase('turn-load')).toBe('turn-load')
    expect(analyticFreshnessForPhase(freshnessAfterAbsent(initialFreshnessState()).phase)).toBe(
      'turn-load'
    )
  })

  it('turns an absent signal into turn load only before accept', () => {
    const turnLoad = freshnessAfterAbsent(initialFreshnessState())
    expect(turnLoad.phase).toBe('turn-load')
    expect(freshnessAfterAbsent(turnLoad)).toBe(turnLoad)

    const current = freshnessAfterAccept(turnLoad)
    expect(current.phase).toBe('current')
    expect(freshnessAfterAbsent(current)).toBe(current)

    const behind = freshnessAfterStoredPaint(initialFreshnessState(), {
      evidenceGeneration: 1,
      evidenceMark: 2,
    })
    expect(behind.phase).toBe('behind-mark')
    expect(freshnessAfterAbsent(behind)).toBe(behind)
  })

  it('maps a stored row to current or behind-mark, never turn load', () => {
    expect(
      freshnessAfterStoredPaint(initialFreshnessState(), {
        evidenceGeneration: 3,
        evidenceMark: 3,
      })
    ).toMatchObject({ phase: 'current', hasStoredRow: true, evidenceGeneration: 3, evidenceMark: 3 })
    expect(
      freshnessAfterStoredPaint(initialFreshnessState(), {
        evidenceGeneration: 1,
        evidenceMark: 2,
      }).phase
    ).toBe('behind-mark')
    expect(
      freshnessAfterStoredPaint(initialFreshnessState(), { evidenceMark: 2 }).phase
    ).toBe('current')
    expect(
      freshnessAfterStoredPaint(initialFreshnessState(), {
        evidenceGeneration: 0,
        evidenceMark: 1,
      })
    ).toMatchObject({ phase: 'behind-mark', hasStoredRow: true, evidenceGeneration: 0 })
    expect(analyticFreshnessForPhase('behind-mark')).toBe('provisional')

    const behind = freshnessAfterStoredPaint(initialFreshnessState(), {
      evidenceGeneration: 1,
      evidenceMark: 2,
    })
    expect(freshnessAfterAccept(behind)).toBe(behind)
    const kept = freshnessAfterStoredPaint(behind, {})
    expect(kept).toMatchObject({
      phase: 'behind-mark',
      hasStoredRow: true,
      evidenceGeneration: 1,
      evidenceMark: 2,
    })
  })

  it('keeps a provisional phase when an absent paint replaces the stored row', () => {
    const behind = freshnessAfterStoredPaint(initialFreshnessState(), {
      evidenceGeneration: 1,
      evidenceMark: 4,
    })
    const sightings = freshnessAfterAbsentPaint(behind, { evidenceMark: 5 })
    expect(sightings).toEqual({
      phase: 'behind-mark',
      hasStoredRow: false,
      evidenceGeneration: 1,
      evidenceMark: 5,
    })
    expect(freshnessAfterAccept(sightings).phase).toBe('current')
    expect(freshnessAfterAccept(sightings).evidenceMark).toBe(5)
  })

  it('paints an unstored result as current and still records a mark', () => {
    const turnLoad = freshnessAfterAbsent(initialFreshnessState())
    const current = freshnessAfterCurrentPaint(turnLoad, { evidenceMark: 4 })
    expect(current).toEqual({
      phase: 'current',
      hasStoredRow: false,
      evidenceGeneration: null,
      evidenceMark: 4,
    })
    expect(freshnessAfterCurrentPaint(current, {})).toEqual(current)
  })
})
