import { describe, expect, it } from 'vitest'
import {
  initialRowStreamState,
  playerIdsFromStableKey,
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

describe('playerIdsFromStableKey', () => {
  it('round-trips sorted player ids', () => {
    expect(playerIdsFromStableKey('8,9')).toEqual([8, 9])
    expect(playerIdsFromStableKey('')).toEqual([])
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

  it('replaces held solutions from complete events when solutions are present', () => {
    const withSolution = reduceRowStreamState(initialRowStreamState(), {
      type: 'solution',
      solutions: [
        {
          objectiveValue: 10,
          actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
        },
      ],
    })
    const complete = reduceRowStreamState(withSolution, {
      type: 'complete',
      status: 'exact',
      summary: 'Best: built warship',
      solutionCount: 1,
      isComplete: true,
      solutions: [
        {
          objectiveValue: 20,
          actions: [{ actionId: 'a2', label: 'Build warship', count: 1 }],
        },
      ],
    })

    expect(complete.isComplete).toBe(true)
    expect(complete.heldSolutions).toHaveLength(1)
    expect(complete.heldSolutions[0]?.actions[0]?.actionId).toBe('a2')
    expect(rowDetailFromStreamState(8, complete).solutionCount).toBe(1)
  })

  it('leaves diagnostics empty on progress events', () => {
    const next = reduceRowStreamState(initialRowStreamState(), {
      type: 'progress',
      policyStepId: 'early_game_bands',
      comboCount: 2142,
      heldCount: 1,
    })

    expect(next.summary).toBe('Searching (early game bands)')
    expect(next.isComplete).toBe(false)
    expect(next.diagnostics).toEqual({})
    expect(rowDetailFromStreamState(11, next).diagnostics).toEqual({})
  })

  it('populates diagnostics only on complete events', () => {
    const complete = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'exact',
      summary: 'Best: Freighter',
      solutionCount: 1,
      isComplete: true,
      diagnostics: {
        turn: 3,
        solver: { status: 'exact', solver_status: 'FREIGHTER_ONLY_FAST_PATH' },
      },
    })

    expect(complete.isComplete).toBe(true)
    expect(complete.diagnostics).toMatchObject({
      turn: 3,
      solver: { status: 'exact' },
    })
  })

  it('updates fleet torp first-class fields when a second complete event arrives', () => {
    const firstComplete = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'exact',
      summary: 'Provisional',
      solutionCount: 1,
      isComplete: true,
      fleetTorpInputStatus: 'pending',
      diagnostics: { fleetTorpInputStatus: 'pending' },
    })
    const secondComplete = reduceRowStreamState(firstComplete, {
      type: 'complete',
      status: 'exact',
      summary: 'Authoritative',
      solutionCount: 1,
      isComplete: true,
      fleetTorpInputStatus: 'applied',
      fleetTorpOverlayBeliefSetTorpIds: [4],
      diagnostics: {
        fleetTorpInputStatus: 'applied',
        fleetTorpOverlay: { beliefSetTorpIds: [4] },
      },
    })

    const detail = rowDetailFromStreamState(8, secondComplete)
    expect(detail.fleetTorpInputStatus).toBe('applied')
    expect(detail.fleetTorpOverlayBeliefSetTorpIds).toEqual([4])
    expect(secondComplete.diagnostics).toMatchObject({
      fleetTorpInputStatus: 'applied',
      fleetTorpOverlay: { beliefSetTorpIds: [4] },
    })
  })

  it('preserves held solutions on complete events without solutions payload', () => {
    const withSolution = reduceRowStreamState(initialRowStreamState(), {
      type: 'solution',
      solutions: [
        {
          objectiveValue: 10,
          actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
        },
      ],
    })
    const complete = reduceRowStreamState(withSolution, {
      type: 'complete',
      status: 'exact',
      summary: 'Done',
      solutionCount: 1,
      isComplete: true,
    })

    expect(complete.heldSolutions).toHaveLength(1)
    expect(complete.heldSolutions[0]?.actions[0]?.actionId).toBe('a1')
  })

  it('marks failure from error events', () => {
    const next = reduceRowStreamState(initialRowStreamState(), {
      type: 'error',
      playerId: 8,
      detail: 'stream ended early',
    })

    expect(next.isComplete).toBe(true)
    expect(next.status).toBe('fetch_error')
    expect(next.summary).toBe('stream ended early')
    expect(rowDetailFromStreamState(8, next).displayStatus).toBe('failure')
  })
})
