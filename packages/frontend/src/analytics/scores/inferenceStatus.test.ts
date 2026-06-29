import { describe, expect, it } from 'vitest'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import {
  canOpenInferenceDetail,
  inferenceAccessibleLabel,
  isActivelySearchingInference,
  isIncompleteInferenceRow,
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

  it('appends fleet torp context for non-not_applicable statuses', () => {
    const base = detail({ summary: 'Best: one build' })
    expect(
      inferenceAccessibleLabel({
        ...base,
        diagnostics: { fleetTorpInputStatus: 'pending' },
      })
    ).toContain('pending')
    expect(
      inferenceAccessibleLabel({
        ...base,
        diagnostics: { fleetTorpInputStatus: 'not_applicable' },
      })
    ).toBe('Best: one build')
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
    expect(
      canOpenInferenceDetail(
        detail({
          displayStatus: 'paused',
          solutionCount: 1,
          solutions: [{ objectiveValue: 1, actions: [] }],
        })
      )
    ).toBe(true)
    expect(canOpenInferenceDetail(detail({ displayStatus: 'pending' }))).toBe(false)
    expect(
      canOpenInferenceDetail(detail({ displayStatus: 'success', solutionCount: 0 }))
    ).toBe(false)
    expect(canOpenInferenceDetail(detail({ displayStatus: 'failure', isComplete: true }))).toBe(
      true
    )
  })
})

describe('incomplete inference row presentation', () => {
  it('treats pending, paused, and in-flight success rows as incomplete', () => {
    expect(isIncompleteInferenceRow(detail({ displayStatus: 'pending', isComplete: false }))).toBe(
      true
    )
    expect(isIncompleteInferenceRow(detail({ displayStatus: 'paused', isComplete: false }))).toBe(
      true
    )
    expect(
      isIncompleteInferenceRow(
        detail({ displayStatus: 'success', solutionCount: 1, isComplete: false })
      )
    ).toBe(true)
    expect(
      isIncompleteInferenceRow(
        detail({ displayStatus: 'success', solutionCount: 1, isComplete: true })
      )
    ).toBe(false)
  })

  it('animates only while actively searching and not globally paused', () => {
    const inFlight = detail({ displayStatus: 'success', solutionCount: 1, isComplete: false })
    expect(isActivelySearchingInference(inFlight)).toBe(true)
    expect(isActivelySearchingInference(inFlight, true)).toBe(false)
    expect(
      isActivelySearchingInference(detail({ displayStatus: 'paused', isComplete: false }))
    ).toBe(false)
    expect(
      isActivelySearchingInference(detail({ displayStatus: 'pending', isComplete: false }), true)
    ).toBe(false)
  })
})
