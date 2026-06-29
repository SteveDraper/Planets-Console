import { describe, expect, it } from 'vitest'
import {
  combineInferenceAccessibleLabel,
  countFleetTorpPendingRows,
  fleetTorpInputAccessibleLabel,
  fleetTorpInputScopeBannerText,
  fleetTorpInputShowsTableIndicator,
  readFleetTorpInputStatus,
  readFleetTorpOverlayBeliefSetTorpIds,
} from './fleetTorpInputStatus'
import type { ScoresInferenceRowDetail } from '../../api/bff'

function rowDetail(
  fleetTorpInputStatus: string | undefined
): ScoresInferenceRowDetail {
  return {
    displayStatus: 'success',
    status: 'exact',
    summary: 'Best: one build',
    solutionCount: 1,
    isComplete: true,
    solutions: [],
    diagnostics:
      fleetTorpInputStatus != null ? { fleetTorpInputStatus } : {},
  }
}

describe('fleetTorpInputAccessibleLabel', () => {
  it('labels all four status values', () => {
    expect(fleetTorpInputAccessibleLabel('not_applicable')).toMatch(/turn 1/)
    expect(fleetTorpInputAccessibleLabel('pending')).toMatch(/pending/)
    expect(fleetTorpInputAccessibleLabel('applied')).toMatch(/persisted fleet snapshot/)
    expect(fleetTorpInputAccessibleLabel('unavailable')).toMatch(/unavailable/)
  })
})

describe('readFleetTorpInputStatus', () => {
  it('parses known wire values and rejects unknown', () => {
    expect(readFleetTorpInputStatus({ fleetTorpInputStatus: 'pending' })).toBe('pending')
    expect(readFleetTorpInputStatus({ fleetTorpInputStatus: 'applied' })).toBe('applied')
    expect(readFleetTorpInputStatus({ fleetTorpInputStatus: 'bogus' })).toBeNull()
  })
})

describe('readFleetTorpOverlayBeliefSetTorpIds', () => {
  it('reads beliefSetTorpIds from fleetTorpOverlay diagnostics', () => {
    expect(
      readFleetTorpOverlayBeliefSetTorpIds({
        fleetTorpOverlay: { beliefSetTorpIds: [4, 8] },
      })
    ).toEqual([4, 8])
    expect(readFleetTorpOverlayBeliefSetTorpIds({})).toBeNull()
  })
})

describe('fleetTorpInputShowsTableIndicator', () => {
  it('shows indicators only for pending and unavailable', () => {
    expect(fleetTorpInputShowsTableIndicator('pending')).toBe(true)
    expect(fleetTorpInputShowsTableIndicator('unavailable')).toBe(true)
    expect(fleetTorpInputShowsTableIndicator('applied')).toBe(false)
    expect(fleetTorpInputShowsTableIndicator('not_applicable')).toBe(false)
  })
})

describe('fleetTorpInputScopeBannerText', () => {
  it('returns null when no rows are pending', () => {
    expect(fleetTorpInputScopeBannerText(0)).toBeNull()
  })

  it('returns singular and plural copy', () => {
    expect(fleetTorpInputScopeBannerText(1)).toMatch(/one player/)
    expect(fleetTorpInputScopeBannerText(3)).toMatch(/3 players/)
  })
})

describe('countFleetTorpPendingRows', () => {
  it('counts rows with pending fleet torp input status', () => {
    expect(
      countFleetTorpPendingRows([
        rowDetail('pending'),
        rowDetail('applied'),
        rowDetail(undefined),
      ])
    ).toBe(1)
  })
})

describe('combineInferenceAccessibleLabel', () => {
  it('appends fleet torp context for non-not_applicable statuses', () => {
    const base = 'Best: one build'
    expect(
      combineInferenceAccessibleLabel(base, { fleetTorpInputStatus: 'pending' })
    ).toContain('pending')
    expect(
      combineInferenceAccessibleLabel(base, { fleetTorpInputStatus: 'not_applicable' })
    ).toBe(base)
  })
})
