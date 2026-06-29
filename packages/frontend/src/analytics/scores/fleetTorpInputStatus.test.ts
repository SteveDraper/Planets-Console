import { describe, expect, it } from 'vitest'
import {
  countFleetTorpPendingRows,
  fleetTorpInputAccessibleLabel,
  fleetTorpInputAnnouncementForTransition,
  fleetTorpInputAppendsToInferenceAccessibleLabel,
  fleetTorpInputScopeBannerText,
  fleetTorpInputShowsTableIndicator,
  parseFleetTorpInputStatus,
  readFleetTorpInputStatusFromDetail,
  readFleetTorpInputStatusFromDiagnostics,
  readFleetTorpOverlayBeliefSetTorpIdsFromDetail,
  readFleetTorpOverlayBeliefSetTorpIdsFromDiagnostics,
} from './fleetTorpInputStatus'
import type { ScoresInferenceRowDetail } from '../../api/bff'

function rowDetail(
  fleetTorpInputStatus: string | undefined,
  beliefSetTorpIds?: number[]
): ScoresInferenceRowDetail {
  return {
    displayStatus: 'success',
    status: 'exact',
    summary: 'Best: one build',
    solutionCount: 1,
    isComplete: true,
    solutions: [],
    diagnostics: {},
    ...(fleetTorpInputStatus != null ? { fleetTorpInputStatus: fleetTorpInputStatus as never } : {}),
    ...(beliefSetTorpIds != null ? { fleetTorpOverlayBeliefSetTorpIds: beliefSetTorpIds } : {}),
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

describe('parseFleetTorpInputStatus', () => {
  it('parses known wire values and rejects unknown', () => {
    expect(parseFleetTorpInputStatus('pending')).toBe('pending')
    expect(parseFleetTorpInputStatus('applied')).toBe('applied')
    expect(parseFleetTorpInputStatus('bogus')).toBeNull()
  })
})

describe('readFleetTorpInputStatusFromDiagnostics', () => {
  it('reads fleet torp status from diagnostics for debug panels', () => {
    expect(
      readFleetTorpInputStatusFromDiagnostics({ fleetTorpInputStatus: 'pending' })
    ).toBe('pending')
  })
})

describe('readFleetTorpInputStatusFromDetail', () => {
  it('reads first-class fleet torp status from row detail', () => {
    expect(readFleetTorpInputStatusFromDetail(rowDetail('pending'))).toBe('pending')
    expect(readFleetTorpInputStatusFromDetail(rowDetail(undefined))).toBeNull()
  })
})

describe('readFleetTorpOverlayBeliefSetTorpIdsFromDiagnostics', () => {
  it('reads beliefSetTorpIds from fleetTorpOverlay diagnostics', () => {
    expect(
      readFleetTorpOverlayBeliefSetTorpIdsFromDiagnostics({
        fleetTorpOverlay: { beliefSetTorpIds: [4, 8] },
      })
    ).toEqual([4, 8])
    expect(readFleetTorpOverlayBeliefSetTorpIdsFromDiagnostics({})).toBeNull()
  })
})

describe('readFleetTorpOverlayBeliefSetTorpIdsFromDetail', () => {
  it('reads first-class belief set torp ids from row detail', () => {
    expect(
      readFleetTorpOverlayBeliefSetTorpIdsFromDetail(rowDetail('applied', [4, 8]))
    ).toEqual([4, 8])
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

describe('fleetTorpInputAppendsToInferenceAccessibleLabel', () => {
  it('appends for pending, applied, and unavailable only', () => {
    expect(fleetTorpInputAppendsToInferenceAccessibleLabel('pending')).toBe(true)
    expect(fleetTorpInputAppendsToInferenceAccessibleLabel('applied')).toBe(true)
    expect(fleetTorpInputAppendsToInferenceAccessibleLabel('unavailable')).toBe(true)
    expect(fleetTorpInputAppendsToInferenceAccessibleLabel('not_applicable')).toBe(false)
  })
})

describe('fleetTorpInputAnnouncementForTransition', () => {
  it('announces entering pending, applied from pending, and unavailable', () => {
    expect(
      fleetTorpInputAnnouncementForTransition('not_applicable', 'pending')
    ).toBe(fleetTorpInputAccessibleLabel('pending'))
    expect(fleetTorpInputAnnouncementForTransition('pending', 'applied')).toBe(
      fleetTorpInputAccessibleLabel('applied')
    )
    expect(
      fleetTorpInputAnnouncementForTransition('pending', 'unavailable')
    ).toBe(fleetTorpInputAccessibleLabel('unavailable'))
  })

  it('is silent for unchanged status and non-announced transitions', () => {
    expect(fleetTorpInputAnnouncementForTransition('pending', 'pending')).toBeNull()
    expect(fleetTorpInputAnnouncementForTransition(null, 'not_applicable')).toBeNull()
    expect(fleetTorpInputAnnouncementForTransition('not_applicable', 'applied')).toBeNull()
    expect(fleetTorpInputAnnouncementForTransition('unavailable', 'unavailable')).toBeNull()
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
