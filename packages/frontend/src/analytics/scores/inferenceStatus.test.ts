import { describe, expect, it } from 'vitest'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import {
  canOpenInferenceDetail,
  inferenceAccessibleLabel,
} from './inferenceStatus'

function detail(
  overrides: Partial<ScoresInferenceRowDetail> = {}
): ScoresInferenceRowDetail {
  return {
    displayStatus: 'failure',
    status: 'no_exact_solution',
    summary: 'No feasible build explanation found',
    solutionCount: 0,
    isComplete: true,
    solutions: [],
    diagnostics: {},
    ...overrides,
  }
}

describe('inferenceAccessibleLabel', () => {
  it('uses summary text for each display status', () => {
    expect(inferenceAccessibleLabel(detail({ summary: 'Best: built one ship' }))).toBe(
      'Best: built one ship'
    )
  })
})

describe('canOpenInferenceDetail', () => {
  it('allows modal only for successful rows with solutions', () => {
    expect(
      canOpenInferenceDetail(
        detail({
          displayStatus: 'success',
          solutionCount: 2,
          solutions: [{ objectiveValue: 1, actions: [] }],
        })
      )
    ).toBe(true)
    expect(canOpenInferenceDetail(detail({ displayStatus: 'pending' }))).toBe(false)
    expect(
      canOpenInferenceDetail(detail({ displayStatus: 'success', solutionCount: 0 }))
    ).toBe(false)
  })
})
