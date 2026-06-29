import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as bff from '../../api/bff'
import {
  scoresInferenceRevisionForScope,
  useScoresInferenceRevisionStore,
} from '../../stores/scoresInferenceRevision'
import {
  TABLE_STREAM_ALREADY_ACTIVE_DETAIL,
  connectTableInferenceStream,
  connectTableInferenceStreamUntilComplete,
  resetLastFleetTorpInputStatusForTests,
} from './tableInferenceStreamConnect'

const scope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

describe('connectTableInferenceStream', () => {
  beforeEach(() => {
    useScoresInferenceRevisionStore.getState().resetRevisions()
    resetLastFleetTorpInputStatusForTests()
  })
  it('retries when the scope-level stream conflict error is returned', async () => {
    const fetchSpy = vi
      .spyOn(bff, 'fetchScoresTableInferenceStream')
      .mockImplementationOnce(async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'error',
          detail: TABLE_STREAM_ALREADY_ACTIVE_DETAIL,
        })
      })
      .mockImplementationOnce(async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          status: 'exact',
          summary: 'ok',
          solutionCount: 1,
          isComplete: true,
        })
      })

    const events: unknown[] = []
    const controller = new AbortController()
    const result = await connectTableInferenceStream(scope, [8], {
      signal: controller.signal,
      onEvent: (event) => {
        events.push(event)
      },
    })

    expect(result).toBe('ok')
    expect(fetchSpy).toHaveBeenCalledTimes(2)
    expect(events).toHaveLength(1)
  })

  it('reconnects when the stream ends before every row is complete', async () => {
    const fetchSpy = vi
      .spyOn(bff, 'fetchScoresTableInferenceStream')
      .mockImplementationOnce(async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          status: 'exact',
          summary: 'cached',
          solutionCount: 1,
          isComplete: true,
        })
      })
      .mockImplementationOnce(async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          status: 'exact',
          summary: 'cached replay',
          solutionCount: 1,
          isComplete: true,
        })
        handlers.onEvent({
          type: 'complete',
          playerId: 6,
          status: 'exact',
          summary: 'after reconnect',
          solutionCount: 1,
          isComplete: true,
        })
      })

    const completedPlayerIds = new Set<number>()
    const controller = new AbortController()
    const result = await connectTableInferenceStreamUntilComplete(scope, [8, 6], {
      signal: controller.signal,
      onEvent: (event) => {
        if (event.type === 'complete' && event.playerId != null) {
          completedPlayerIds.add(event.playerId)
        }
      },
      hasPendingRows: () => [8, 6].some((playerId) => !completedPlayerIds.has(playerId)),
    })

    expect(result).toBe('ok')
    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })

  it('bumps scores inference revision on complete but not on every solution', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'progress',
          playerId: 8,
          policyStepId: 'early_game_bands',
        })
        handlers.onEvent({
          type: 'solution',
          playerId: 8,
          solutions: [],
        })
        handlers.onEvent({
          type: 'solution',
          playerId: 8,
          solutions: [],
        })
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          status: 'exact',
          summary: 'done',
          solutionCount: 1,
          isComplete: true,
        })
      }
    )

    const controller = new AbortController()
    await connectTableInferenceStream(scope, [8], {
      signal: controller.signal,
      onEvent: () => {},
    })

    expect(scoresInferenceRevisionForScope(scope)).toBe(1)
  })

  it('bumps scores inference revision on solution when fleet torp status changes', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'solution',
          playerId: 8,
          solutions: [],
          fleetTorpInputStatus: 'pending',
        })
        handlers.onEvent({
          type: 'solution',
          playerId: 8,
          solutions: [],
          fleetTorpInputStatus: 'pending',
        })
        handlers.onEvent({
          type: 'solution',
          playerId: 8,
          solutions: [],
          fleetTorpInputStatus: 'applied',
        })
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          status: 'exact',
          summary: 'done',
          solutionCount: 1,
          isComplete: true,
          fleetTorpInputStatus: 'applied',
        })
      }
    )

    const controller = new AbortController()
    await connectTableInferenceStream(scope, [8], {
      signal: controller.signal,
      onEvent: () => {},
    })

    expect(scoresInferenceRevisionForScope(scope)).toBe(3)
  })

  it('does not bump scores inference revision on scope-level stream conflict errors', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream')
      .mockImplementationOnce(async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'error',
          detail: TABLE_STREAM_ALREADY_ACTIVE_DETAIL,
        })
      })
      .mockImplementationOnce(async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          status: 'exact',
          summary: 'ok',
          solutionCount: 1,
          isComplete: true,
        })
      })

    const controller = new AbortController()
    await connectTableInferenceStream(scope, [8], {
      signal: controller.signal,
      onEvent: () => {},
    })

    expect(scoresInferenceRevisionForScope(scope)).toBe(1)
  })
})
