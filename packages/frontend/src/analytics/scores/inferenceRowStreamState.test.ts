import { describe, expect, it } from 'vitest'
import { inferenceStreamEventSchema } from '../../api/inferenceStreamEventSchema'
import {
  initialRowStreamState,
  pointUnexplainedMilitaryDelta2x,
  reduceRowStreamState,
  rowDetailFromStreamState,
} from './inferenceRowStreamState'

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

  it('shows zero-solution time_limited complete as a visible failure', () => {
    const next = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'time_limited',
      displayStatus: 'failure',
      summary: 'Inference timed out before finding a solution',
      solutionCount: 0,
      isComplete: true,
    })
    const detail = rowDetailFromStreamState(4, next)
    expect(detail.displayStatus).toBe('failure')
    expect(detail.isComplete).toBe(true)
    expect(detail.summary).toMatch(/timed out/i)
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
      displayStatus: 'success',
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
      displayStatus: 'success',
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
      displayStatus: 'success',
      summary: 'Provisional',
      solutionCount: 1,
      isComplete: true,
      fleetTorpInputStatus: 'pending',
      diagnostics: { fleetTorpInputStatus: 'pending' },
    })
    const secondComplete = reduceRowStreamState(firstComplete, {
      type: 'complete',
      status: 'exact',
      displayStatus: 'success',
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
      displayStatus: 'success',
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
    expect(next.isStreamSettled).toBe(true)
    expect(next.status).toBe('fetch_error')
    expect(next.summary).toBe('stream ended early')
    expect(rowDetailFromStreamState(8, next).displayStatus).toBe('failure')
  })

  it('maps skip complete to skipped display status without opening solutions', () => {
    const next = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'dead',
      displayStatus: 'skipped',
      summary: 'Player is dead',
      solutionCount: 0,
      isComplete: true,
      solutions: [],
      placeholders: [],
    })
    const detail = rowDetailFromStreamState(4, next)
    expect(detail.displayStatus).toBe('skipped')
    expect(detail.solutionCount).toBe(0)
    expect(detail.placeholders).toEqual([])
  })

  it('does not reclassify Core skip statuses when BFF stamps failure', () => {
    const next = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'dead',
      displayStatus: 'failure',
      summary: 'Player is dead',
      solutionCount: 0,
      isComplete: true,
      solutions: [],
      placeholders: [],
    })
    expect(rowDetailFromStreamState(4, next).displayStatus).toBe('failure')
  })

  it('maps unknown complete without a skip stamp to failure', () => {
    const next = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'novel_terminal',
      displayStatus: 'failure',
      summary: 'unrecognized complete',
      solutionCount: 0,
      isComplete: true,
    })
    expect(rowDetailFromStreamState(4, next).displayStatus).toBe('failure')
  })

  it('maps residual complete to residual display status with leftover', () => {
    const next = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'moderate_residual',
      displayStatus: 'moderate_residual',
      summary: 'Moderate military leftover (11)',
      solutionCount: 0,
      isComplete: true,
      solutions: [],
      placeholders: [],
      unexplainedMilitaryDelta2x: 22,
    })
    const detail = rowDetailFromStreamState(4, next)
    expect(detail.displayStatus).toBe('moderate_residual')
    expect(detail.unexplainedMilitaryDelta2x).toBe(22)
    expect(detail.placeholders).toEqual([])
  })

  it('maps mine-score residual complete with ship-first solutions without flipping to success', () => {
    const next = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'mine_score_residual',
      displayStatus: 'mine_score_residual',
      summary: 'Mine-score leftover (27)',
      solutionCount: 2,
      isComplete: true,
      solutions: [
        {
          objectiveValue: 10,
          actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
          shipFirstFamily: 'mine_overshoot',
        },
        {
          objectiveValue: 8,
          actions: [{ actionId: 'a2', label: 'Load torps', count: 1 }],
          shipFirstFamily: 'ammo_top_up',
        },
      ],
      placeholders: [],
      unexplainedMilitaryDelta2x: 54,
    })
    const detail = rowDetailFromStreamState(4, next)
    expect(detail.displayStatus).toBe('mine_score_residual')
    expect(detail.solutionCount).toBe(2)
    expect(detail.solutions[0]?.shipFirstFamily).toBe('mine_overshoot')
    expect(detail.unexplainedMilitaryDelta2x).toBe(54)
  })

  it('shows held time_limited complete using BFF success chrome', () => {
    const next = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'time_limited',
      displayStatus: 'success',
      summary: 'Timed out with held solutions',
      solutionCount: 1,
      isComplete: true,
      solutions: [
        {
          objectiveValue: 10,
          actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
        },
      ],
    })
    expect(rowDetailFromStreamState(8, next).displayStatus).toBe('success')
  })

  it('stamps uncharacterized roster complete with bound leftover, not a point leftover', () => {
    const next = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'uncharacterized_roster',
      displayStatus: 'uncharacterized_roster',
      summary: 'Uncharacterized roster',
      solutionCount: 0,
      isComplete: true,
      solutions: [],
      leftover: { kind: 'unknown_loss_bound', lowerBound2x: 800 },
      unexplainedMilitaryDelta2x: 800,
      placeholders: [{ id: 'placeholder_departure', shipClass: 'warship', count: 1 }],
      latticeSignatures: [
        {
          shipClass: 'warship',
          build: {
            id: 'unknown_military_ship',
            hullId: -1,
            count: 1,
            buildSlotUsage: 1,
          },
          departure: {
            id: 'placeholder_departure',
            shipClass: 'warship',
            count: 1,
          },
        },
      ],
    })
    const detail = rowDetailFromStreamState(4, next)
    expect(detail.displayStatus).toBe('uncharacterized_roster')
    expect(detail.leftover).toEqual({ kind: 'unknown_loss_bound', lowerBound2x: 800 })
    expect(detail.unexplainedMilitaryDelta2x).toBeUndefined()
    expect(detail.latticeSignatures).toHaveLength(1)
    expect(detail.solutionCount).toBe(0)
  })

  it('clears a prior point leftover alias when a later complete is bound leftover', () => {
    const residual = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'moderate_residual',
      displayStatus: 'moderate_residual',
      summary: 'Moderate military leftover (11)',
      solutionCount: 0,
      isComplete: true,
      unexplainedMilitaryDelta2x: 22,
    })
    const bound = reduceRowStreamState(residual, {
      type: 'complete',
      status: 'uncharacterized_roster',
      displayStatus: 'uncharacterized_roster',
      summary: 'Uncharacterized roster',
      solutionCount: 0,
      isComplete: true,
      leftover: { kind: 'unknown_loss_bound', lowerBound2x: 800 },
    })
    expect(rowDetailFromStreamState(4, residual).unexplainedMilitaryDelta2x).toBe(22)
    expect(rowDetailFromStreamState(4, bound).unexplainedMilitaryDelta2x).toBeUndefined()
  })

  it('omits a point leftover alias from row detail when leftover is already bound', () => {
    const detail = rowDetailFromStreamState(4, {
      ...initialRowStreamState(),
      status: 'uncharacterized_roster',
      displayStatus: 'uncharacterized_roster',
      summary: 'Uncharacterized roster',
      isComplete: true,
      leftover: { kind: 'unknown_loss_bound', lowerBound2x: 800 },
      unexplainedMilitaryDelta2x: 800,
    })
    expect(detail.leftover).toEqual({ kind: 'unknown_loss_bound', lowerBound2x: 800 })
    expect(detail.unexplainedMilitaryDelta2x).toBeUndefined()
  })

  it('shows no freshness word before the no-stored prelude, then turn load until accept', () => {
    expect(rowDetailFromStreamState(3, initialRowStreamState()).freshness).toBeUndefined()
    expect(inferenceStreamEventSchema.safeParse({ type: 'no_stored_row', playerId: 3 }).success).toBe(
      true
    )
    const loading = reduceRowStreamState(initialRowStreamState(), { type: 'no_stored_row' })
    expect(rowDetailFromStreamState(3, loading).freshness).toBe('turn-load')
    const accepted = reduceRowStreamState(loading, { type: 'work_accepted' })
    expect(rowDetailFromStreamState(3, accepted).freshness).toBeUndefined()
    expect(rowDetailFromStreamState(3, accepted).displayStatus).toBe('pending')
  })

  it('keeps no freshness word when no_stored_row arrives again after accept', () => {
    const loading = reduceRowStreamState(initialRowStreamState(), { type: 'no_stored_row' })
    const accepted = reduceRowStreamState(loading, { type: 'work_accepted' })
    const again = reduceRowStreamState(accepted, { type: 'no_stored_row' })
    expect(again).toBe(accepted)
    expect(rowDetailFromStreamState(3, again).freshness).toBeUndefined()
  })

  it('does not return a stored row to turn load when no_stored_row arrives', () => {
    const stored = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'exact',
      displayStatus: 'success',
      summary: 'Best build',
      solutionCount: 1,
      isComplete: true,
      evidenceGeneration: 1,
      evidenceMark: 2,
    })
    const again = reduceRowStreamState(stored, { type: 'no_stored_row' })
    expect(again).toBe(stored)
    expect(rowDetailFromStreamState(4, again).freshness).toBe('provisional')
  })

  it('keeps provisional and stored evidence when progress reopens a complete row', () => {
    const stored = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'exact',
      displayStatus: 'success',
      summary: 'Best build',
      solutionCount: 1,
      isComplete: true,
      evidenceGeneration: 1,
      evidenceMark: 2,
    })
    const searching = reduceRowStreamState(stored, {
      type: 'progress',
      policyStepId: 'tier_1',
    })
    expect(searching.freshness.hasStoredRow).toBe(true)
    expect(searching.freshness.evidenceGeneration).toBe(1)
    expect(searching.freshness.evidenceMark).toBe(2)
    expect(searching.isComplete).toBe(false)
    expect(searching.displayStatus).toBe('pending')
    const detail = rowDetailFromStreamState(4, searching)
    expect(detail.freshness).toBe('provisional')

    const withSolution = reduceRowStreamState(stored, {
      type: 'solution',
      solutions: [
        {
          objectiveValue: 10,
          actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
        },
      ],
    })
    expect(withSolution.freshness.hasStoredRow).toBe(true)
    expect(withSolution.freshness.evidenceGeneration).toBe(1)
    expect(withSolution.freshness.evidenceMark).toBe(2)
    expect(rowDetailFromStreamState(4, withSolution).freshness).toBe('provisional')
    expect(rowDetailFromStreamState(4, withSolution).displayStatus).toBe('pending')
  })

  it('keeps provisional across a stored prelude and the following accept', () => {
    const solution = {
      objectiveValue: 1,
      actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
    }
    const painted = reduceRowStreamState(initialRowStreamState(), {
      type: 'stored_row',
      status: 'exact',
      displayStatus: 'success',
      summary: 'Best build',
      solutionCount: 1,
      isComplete: true,
      evidenceGeneration: 1,
      evidenceMark: 2,
      solutions: [solution],
    })
    const paintedDetail = rowDetailFromStreamState(4, painted)
    expect(paintedDetail.freshness).toBe('provisional')
    expect(paintedDetail.displayStatus).toBe('success')
    expect(paintedDetail.solutionCount).toBe(1)
    expect(paintedDetail.isComplete).toBe(true)
    expect(painted.isStreamSettled).toBe(false)

    const accepted = reduceRowStreamState(painted, { type: 'work_accepted' })
    const busy = rowDetailFromStreamState(4, accepted)
    expect(busy.freshness).toBe('provisional')
    expect(busy.displayStatus).toBe('pending')
    expect(busy.isComplete).toBe(false)
    expect(accepted.isStreamSettled).toBe(false)

    const finished = reduceRowStreamState(accepted, {
      type: 'complete',
      status: 'exact',
      displayStatus: 'success',
      summary: 'Recomputed build',
      solutionCount: 1,
      isComplete: true,
      evidenceGeneration: 2,
      evidenceMark: 2,
      solutions: [solution],
    })
    expect(finished.isStreamSettled).toBe(true)
    expect(rowDetailFromStreamState(4, finished).freshness).toBeUndefined()

    const recomputing = reduceRowStreamState(finished, { type: 'work_accepted' })
    expect(recomputing.isStreamSettled).toBe(false)
    expect(rowDetailFromStreamState(4, recomputing).displayStatus).toBe('pending')

    const skip = reduceRowStreamState(initialRowStreamState(), {
      type: 'stored_row',
      status: 'dead',
      displayStatus: 'skipped',
      summary: 'Player is dead',
      solutionCount: 0,
      isComplete: true,
      evidenceGeneration: 0,
      evidenceMark: 1,
      solutions: [],
    })
    const skipDetail = rowDetailFromStreamState(4, skip)
    expect(skipDetail.displayStatus).toBe('skipped')
    expect(skipDetail.freshness).toBe('provisional')
    expect(skipDetail.isComplete).toBe(true)
    expect(skip.isStreamSettled).toBe(false)

    const onMark = reduceRowStreamState(initialRowStreamState(), {
      type: 'stored_row',
      status: 'exact',
      displayStatus: 'success',
      summary: 'Best build',
      solutionCount: 1,
      isComplete: true,
      evidenceGeneration: 3,
      evidenceMark: 3,
      solutions: [solution],
    })
    expect(rowDetailFromStreamState(4, onMark).freshness).toBeUndefined()
    expect(rowDetailFromStreamState(4, onMark).displayStatus).toBe('success')

    const onMarkAccepted = reduceRowStreamState(onMark, { type: 'work_accepted' })
    const onMarkBusy = rowDetailFromStreamState(4, onMarkAccepted)
    expect(onMarkBusy.summary).toBe('Build inference in progress')
    expect(onMarkBusy.freshness).toBeUndefined()
    expect(onMarkBusy.displayStatus).toBe('pending')
  })

  it('keeps Provisional beside a stored row that is behind the mark', () => {
    const stored = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'exact',
      displayStatus: 'success',
      summary: 'Best build',
      solutionCount: 1,
      isComplete: true,
      evidenceGeneration: 1,
      evidenceMark: 2,
    })
    expect(rowDetailFromStreamState(4, stored).freshness).toBe('provisional')

    const recomputing = reduceRowStreamState(stored, { type: 'work_accepted' })
    const detail = rowDetailFromStreamState(4, recomputing)
    expect(detail.freshness).toBe('provisional')
    expect(detail.displayStatus).toBe('pending')
  })

  it('shows Provisional beside a stored skip and nothing beside an unmarked skip', () => {
    const storedSkip = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'dead',
      displayStatus: 'skipped',
      summary: 'Player is dead',
      solutionCount: 0,
      isComplete: true,
      evidenceGeneration: 0,
      evidenceMark: 1,
    })
    expect(rowDetailFromStreamState(4, storedSkip).freshness).toBe('provisional')
    expect(rowDetailFromStreamState(4, storedSkip).displayStatus).toBe('skipped')

    const unmarkedSkip = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'dead',
      displayStatus: 'skipped',
      summary: 'Player is dead',
      solutionCount: 0,
      isComplete: true,
    })
    expect(rowDetailFromStreamState(4, unmarkedSkip).freshness).toBeUndefined()
    expect(rowDetailFromStreamState(4, unmarkedSkip).displayStatus).toBe('skipped')
  })

  it('treats a stored row on the current mark as complete, including an approximate fleet', () => {
    const onMark = reduceRowStreamState(initialRowStreamState(), {
      type: 'complete',
      status: 'exact',
      displayStatus: 'success',
      summary: 'Best build',
      solutionCount: 1,
      isComplete: true,
      evidenceGeneration: 3,
      evidenceMark: 3,
    })
    expect(rowDetailFromStreamState(4, onMark).freshness).toBeUndefined()
  })
})

describe('pointUnexplainedMilitaryDelta2x', () => {
  it('is the only bound leftover omit branch', () => {
    expect(
      pointUnexplainedMilitaryDelta2x({ kind: 'unknown_loss_bound', lowerBound2x: 800 }, 800)
    ).toBeUndefined()
    expect(
      pointUnexplainedMilitaryDelta2x({ kind: 'point', unexplainedMilitaryDelta2x: 22 }, 22)
    ).toBe(22)
    expect(pointUnexplainedMilitaryDelta2x(undefined, 54)).toBe(54)
    expect(pointUnexplainedMilitaryDelta2x(undefined, undefined)).toBeUndefined()
  })
})
