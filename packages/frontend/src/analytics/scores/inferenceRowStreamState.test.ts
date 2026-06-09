import { describe, expect, it } from 'vitest'
import { isActivelySearchingInference } from './inferenceStatus'
import {
  initialRowStreamState,
  reduceRowStreamState,
  rowDetailFromStreamState,
  stablePlayerIdsKey,
} from './inferenceRowStreamState'

describe('stablePlayerIdsKey', () => {
  it('sorts ids so order changes do not alter the key', () => {
    expect(stablePlayerIdsKey([9, 8])).toBe('8,9')
    expect(stablePlayerIdsKey([8, 9])).toBe('8,9')
  })
})

describe('reduceRowStreamState', () => {
  it('ignores non-target accelerated segment solutions for held top-K', () => {
    const state = initialRowStreamState()
    const next = reduceRowStreamState(state, {
      type: 'solution',
      segmentId: 'accel_window',
      scoreboardDeltaSource: 'accelerated_segment',
      isTargetSegment: false,
      solutions: [
        {
          objectiveValue: 10,
          actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
        },
      ],
    })

    expect(next.heldSolutions).toHaveLength(0)
    const detail = rowDetailFromStreamState(8, next)
    expect(detail.solutionCount).toBe(0)
    expect(detail.diagnostics.streamInterimSegmentProgress).toBe(true)
    expect(isActivelySearchingInference(detail)).toBe(false)
  })

  it('updates held top-K from target accelerated segment solutions', () => {
    const interim = reduceRowStreamState(initialRowStreamState(), {
      type: 'solution',
      segmentId: 'accel_window',
      isTargetSegment: false,
      solutions: [
        {
          objectiveValue: 10,
          actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
        },
      ],
    })
    const next = reduceRowStreamState(interim, {
      type: 'solution',
      segmentId: 'reported_host_turn',
      isTargetSegment: true,
      solutions: [
        {
          objectiveValue: 12,
          actions: [{ actionId: 'a2', label: 'Build warship', count: 1 }],
        },
      ],
    })

    expect(next.heldSolutions).toHaveLength(1)
    expect(next.heldSolutions[0]?.actions[0]?.actionId).toBe('a2')
    const detail = rowDetailFromStreamState(8, next)
    expect(detail.solutionCount).toBe(1)
    expect(detail.diagnostics.streamInterimSegmentProgress).toBeUndefined()
  })

  it('replaces held solutions wholesale on solution events', () => {
    const state = initialRowStreamState()
    const next = reduceRowStreamState(state, {
      type: 'solution',
      solutions: [
        {
          objectiveValue: 10,
          actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
        },
      ],
    })

    expect(next.heldSolutions).toHaveLength(1)
    expect(rowDetailFromStreamState(8, next).solutionCount).toBe(1)
    expect(rowDetailFromStreamState(8, next).displayStatus).toBe('success')
  })

  it('marks paused rows without clearing held solutions', () => {
    const withSolution = reduceRowStreamState(initialRowStreamState(), {
      type: 'solution',
      solutions: [
        {
          objectiveValue: 10,
          actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
        },
      ],
    })
    const paused = reduceRowStreamState(withSolution, { type: 'globalPause', paused: true })

    expect(paused.status).toBe('paused')
    expect(paused.heldSolutions).toHaveLength(1)
  })
})
