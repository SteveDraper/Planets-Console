import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as bff from '../../api/bff'
import {
  scoresInferenceRevisionForScope,
  useScoresInferenceRevisionStore,
} from '../../stores/scoresInferenceRevision'
import {
  connectTableInferenceStream,
  connectTableInferenceStreamUntilComplete,
} from './tableInferenceStreamConnect'

const scope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

describe('connectTableInferenceStream', () => {
  beforeEach(() => {
    useScoresInferenceRevisionStore.getState().resetRevisions()
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

  it('bumps scores inference revision on held solution changes and every complete', async () => {
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
          type: 'solution',
          playerId: 8,
          solutions: [{ objectiveValue: 1, actions: [] }],
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

    expect(scoresInferenceRevisionForScope(scope)).toBe(3)
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

  it('bumps scores inference revision for each player complete in a multi-player stream', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          status: 'exact',
          summary: 'player 8 done',
          solutionCount: 1,
          isComplete: true,
          fleetTorpInputStatus: 'applied',
        })
        handlers.onEvent({
          type: 'complete',
          playerId: 6,
          status: 'exact',
          summary: 'player 6 done',
          solutionCount: 1,
          isComplete: true,
          fleetTorpInputStatus: 'applied',
        })
      }
    )

    const controller = new AbortController()
    await connectTableInferenceStream(scope, [8, 6], {
      signal: controller.signal,
      onEvent: () => {},
    })

    expect(scoresInferenceRevisionForScope(scope)).toBe(2)
  })

  it('bumps scores inference revision per player on first fleet torp status at solution time', async () => {
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
          playerId: 6,
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
          playerId: 6,
          solutions: [],
          fleetTorpInputStatus: 'pending',
        })
      }
    )

    const controller = new AbortController()
    await connectTableInferenceStream(scope, [8, 6], {
      signal: controller.signal,
      onEvent: () => {},
    })

    expect(scoresInferenceRevisionForScope(scope)).toBe(2)
  })
})
