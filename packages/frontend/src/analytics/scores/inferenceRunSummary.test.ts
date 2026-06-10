import { describe, expect, it } from 'vitest'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import {
  formatInferenceStatusLabel,
  readInferenceRunSummary,
} from './inferenceRunSummary'

function rowDetail(
  overrides: Partial<ScoresInferenceRowDetail> = {}
): ScoresInferenceRowDetail {
  return {
    displayStatus: 'success',
    status: 'exact',
    summary: '',
    solutionCount: 0,
    isComplete: true,
    solutions: [],
    diagnostics: {},
    ...overrides,
  }
}

describe('formatInferenceStatusLabel', () => {
  it('replaces underscores with spaces', () => {
    expect(formatInferenceStatusLabel('solver_stopped')).toBe('solver stopped')
  })
})

describe('readInferenceRunSummary', () => {
  it('prefers row status over solver sub-status fields', () => {
    const summary = readInferenceRunSummary(
      rowDetail({ status: 'exact' }),
      {
        solver: {
          status: 'exact',
          solver_status: 'INFEASIBLE',
          solverStatus: 'TIME_LIMIT',
          wall_time_seconds: 0.12,
        },
      }
    )

    expect(summary).toEqual({
      statusLabel: 'exact',
      wallTimeSeconds: 0.12,
    })
  })

  it('falls back through solver status keys when row status is empty', () => {
    expect(
      readInferenceRunSummary(rowDetail({ status: '' }), {
        solver: { status: 'partial', solver_status: 'INFEASIBLE' },
      }).statusLabel
    ).toBe('partial')

    expect(
      readInferenceRunSummary(rowDetail({ status: '' }), {
        solver: { solver_status: 'INFEASIBLE', solverStatus: 'TIME_LIMIT' },
      }).statusLabel
    ).toBe('INFEASIBLE')

    expect(
      readInferenceRunSummary(rowDetail({ status: '' }), {
        solver: { solverStatus: 'TIME_LIMIT' },
      }).statusLabel
    ).toBe('TIME LIMIT')
  })

  it('reads wall time from snake_case or camelCase solver keys', () => {
    expect(
      readInferenceRunSummary(rowDetail(), {
        solver: { wall_time_seconds: 1.25 },
      }).wallTimeSeconds
    ).toBe(1.25)

    expect(
      readInferenceRunSummary(rowDetail(), {
        solver: { wallTimeSeconds: 2.5 },
      }).wallTimeSeconds
    ).toBe(2.5)
  })

  it('returns undefined labels when no status is available', () => {
    expect(readInferenceRunSummary(rowDetail({ status: '' }), {})).toEqual({})
    expect(readInferenceRunSummary(rowDetail({ status: '' }), { solver: {} })).toEqual({})
  })
})
