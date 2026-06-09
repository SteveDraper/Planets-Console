import { describe, expect, it } from 'vitest'
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

  it('updates held top-K from target accelerated segment solutions', () => {
    const next = reduceRowStreamState(initialRowStreamState(), {
      type: 'solution',
      segmentId: 'reported_host_turn',
      solutions: [
        {
          objectiveValue: 12,
          actions: [{ actionId: 'a2', label: 'Build warship', count: 1 }],
        },
      ],
    })

    expect(next.heldSolutions).toHaveLength(1)
    expect(next.heldSolutions[0]?.actions[0]?.actionId).toBe('a2')
    expect(rowDetailFromStreamState(8, next).solutionCount).toBe(1)
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
