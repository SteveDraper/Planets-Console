import { describe, expect, it } from 'vitest'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import {
  isCompleteShipFirstResidualList,
  shipFirstFamilyChipLabel,
  shipFirstListMixesFamilies,
  shipFirstResidualAccessibleLabel,
} from './shipFirstFamilyChrome'

function residualDetail(
  overrides: Partial<ScoresInferenceRowDetail> = {}
): ScoresInferenceRowDetail {
  return {
    displayStatus: 'mine_score_residual',
    status: 'mine_score_residual',
    summary: 'Mine-score leftover (27)',
    solutionCount: 2,
    isComplete: true,
    solutions: [
      { objectiveValue: 10, actions: [], shipFirstFamily: 'mine_overshoot' },
      { objectiveValue: 8, actions: [], shipFirstFamily: 'ammo_top_up' },
    ],
    diagnostics: {},
    unexplainedMilitaryDelta2x: 54,
    ...overrides,
  }
}

describe('shipFirstFamilyChrome', () => {
  it('maps Core family tags to chip copy without re-deriving', () => {
    expect(shipFirstFamilyChipLabel('mine_overshoot')).toBe('Mine leftover')
    expect(shipFirstFamilyChipLabel('ammo_top_up')).toBe('Ammo top-up')
  })

  it('detects a mixed-family held list', () => {
    expect(shipFirstListMixesFamilies(residualDetail().solutions)).toBe(true)
    expect(
      shipFirstListMixesFamilies([
        { objectiveValue: 10, actions: [], shipFirstFamily: 'mine_overshoot' },
      ])
    ).toBe(false)
  })

  it('treats complete mine-score residual with N>0 as the blue-badge list', () => {
    expect(isCompleteShipFirstResidualList(residualDetail())).toBe(true)
    expect(
      isCompleteShipFirstResidualList(
        residualDetail({ solutionCount: 0, solutions: [] })
      )
    ).toBe(false)
    expect(
      isCompleteShipFirstResidualList(
        residualDetail({
          displayStatus: 'moderate_residual',
          status: 'moderate_residual',
        })
      )
    ).toBe(false)
  })

  it('names count first, leftover second, and the mix when both families are held', () => {
    expect(shipFirstResidualAccessibleLabel(residualDetail())).toBe(
      '2 probable builds. Mix of mine leftover and ammo top-up. Leftover 27.'
    )
    expect(
      shipFirstResidualAccessibleLabel(
        residualDetail({
          solutionCount: 1,
          solutions: [
            { objectiveValue: 10, actions: [], shipFirstFamily: 'mine_overshoot' },
          ],
        })
      )
    ).toBe('1 probable build. Leftover 27.')
  })
})
