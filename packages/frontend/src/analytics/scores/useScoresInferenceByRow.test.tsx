import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope, TableDataResponse } from '../../api/bff'
import * as bff from '../../api/bff'
import type { InferenceStreamEvent } from '../../api/inferenceStreamEventSchema'
import { useScoresInferenceByRow } from './useScoresInferenceByRow'

type StreamHandlers = Parameters<typeof bff.fetchScoresTableInferenceStream>[2]

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function longLivedTableStream(
  emitPhases: Array<(handlers: StreamHandlers) => void | Promise<void>>
): () => number {
  let streamCallCount = 0

  vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
    async (_scope, _playerIds, handlers) => {
      streamCallCount += 1
      for (const emitPhase of emitPhases) {
        await emitPhase(handlers)
        await delay(0)
      }
      await new Promise<void>((resolve) => {
        handlers.signal?.addEventListener('abort', () => {
          resolve()
        })
      })
    }
  )

  return () => streamCallCount
}

function emitComplete(
  onEvent: StreamHandlers['onEvent'],
  playerId: number,
  summary: string,
  diagnostics?: Record<string, unknown>
): void {
  onEvent({
    type: 'complete',
    playerId,
    status: 'exact',
    summary,
    solutionCount: 1,
    isComplete: true,
    ...(diagnostics != null ? { diagnostics } : {}),
  })
}

function emitSolution(onEvent: StreamHandlers['onEvent'], playerId: number): void {
  onEvent({
    type: 'solution',
    playerId,
    solutions: [
      {
        objectiveValue: 10,
        actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
      },
    ],
  })
}

function emitProgress(
  onEvent: StreamHandlers['onEvent'],
  playerId: number,
  policyStepId = 'tier_1'
): void {
  onEvent({
    type: 'progress',
    playerId,
    policyStepId,
  })
}

function emitGlobalPause(
  onEvent: StreamHandlers['onEvent'],
  paused: boolean
): void {
  onEvent({ type: 'globalPause', paused } satisfies InferenceStreamEvent)
}

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

const tableData: TableDataResponse = {
  analyticId: 'scores',
  includeBuildInference: true,
  columns: ['Race (player)', 'Build inference'],
  rows: [['Alice']],
  inferenceByRow: [{ playerId: 8 }, { playerId: 9 }],
}

describe('useScoresInferenceByRow', () => {
  it('returns pending while the table inference stream is in flight', () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      () => new Promise(() => {})
    )

    const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

    expect(result.current.inferenceByRow).toHaveLength(2)
    expect(result.current.inferenceByRow?.[0]).toMatchObject({
      playerId: 8,
      displayStatus: 'pending',
    })
    expect(result.current.inferenceByRow?.[1]).toMatchObject({
      playerId: 9,
      displayStatus: 'pending',
    })
  })

  it('merges settled inference independently per player from the table stream', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          status: 'exact',
          summary: 'Player 8 ok',
          solutionCount: 1,
          isComplete: true,
        })
        handlers.onEvent({
          type: 'error',
          playerId: 9,
          detail: '502 player 9 failed',
        })
      }
    )

    const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('success')
      expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('failure')
    })
    expect(result.current.inferenceByRow?.[0]?.summary).toBe('Player 8 ok')
    expect(result.current.inferenceByRow?.[1]?.summary).toContain('502')
  })

  it('shows count badge when first solution arrives before complete', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'solution',
          playerId: 8,
          solutions: [
            {
              objectiveValue: 10,
              actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
            },
          ],
        })
        await new Promise(() => {})
      }
    )

    const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.solutionCount).toBe(1)
      expect(result.current.inferenceByRow?.[0]?.isComplete).toBe(false)
    })
  })

  it('pauses in-progress rows from globalPause stream events', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'solution',
          playerId: 8,
          solutions: [
            {
              objectiveValue: 10,
              actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
            },
          ],
        })
        handlers.onEvent({ type: 'globalPause', paused: true })
        await new Promise(() => {})
      }
    )

    const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('paused')
      expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('paused')
    })
    expect(result.current.inferenceByRow?.[0]?.summary).toBe('Paused with 1 held solution(s)')
    expect(result.current.inferenceByRow?.[1]?.summary).toBe('Build inference paused')
  })

  it('resumes paused rows from globalPause stream events', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({ type: 'globalPause', paused: true })
        handlers.onEvent({ type: 'globalPause', paused: false })
        await new Promise(() => {})
      }
    )

    const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('pending')
      expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('pending')
    })
    expect(result.current.inferenceByRow?.[0]?.summary).toBe('Build inference in progress')
  })

  it('does not pause complete rows on globalPause stream events', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          status: 'exact',
          summary: 'Player 8 ok',
          solutionCount: 1,
          isComplete: true,
        })
        handlers.onEvent({ type: 'globalPause', paused: true })
        await new Promise(() => {})
      }
    )

    const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('success')
      expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('paused')
    })
  })

  it('notifies onGlobalPauseChange from globalPause stream events', async () => {
    const onGlobalPauseChange = vi.fn()
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({ type: 'globalPause', paused: true })
        handlers.onEvent({ type: 'globalPause', paused: false })
        await new Promise(() => {})
      }
    )

    renderHook(() =>
      useScoresInferenceByRow(tableData, scope, true, { onGlobalPauseChange })
    )

    await waitFor(() => {
      expect(onGlobalPauseChange).toHaveBeenCalledWith(true)
      expect(onGlobalPauseChange).toHaveBeenLastCalledWith(false)
    })
  })

  it('applies scope-level stream errors to every row', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'error',
          detail: 'Inference table stream failed',
        })
      }
    )

    const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('failure')
      expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('failure')
    })
    expect(result.current.inferenceByRow?.[0]?.summary).toBe('Inference table stream failed')
  })

  it('resets global pause when the table stream ends', () => {
    const onGlobalPauseChange = vi.fn()
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      () => new Promise(() => {})
    )

    const { unmount } = renderHook(() =>
      useScoresInferenceByRow(tableData, scope, true, { onGlobalPauseChange })
    )

    unmount()

    expect(onGlobalPauseChange).toHaveBeenCalledWith(false)
  })

  it('resets global pause when inference is disabled', () => {
    const onGlobalPauseChange = vi.fn()
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      () => new Promise(() => {})
    )

    const { rerender } = renderHook(
      ({ enabled }) =>
        useScoresInferenceByRow(tableData, scope, enabled, { onGlobalPauseChange }),
      { initialProps: { enabled: true } }
    )

    onGlobalPauseChange.mockClear()
    rerender({ enabled: false })

    expect(onGlobalPauseChange).toHaveBeenCalledWith(false)
  })

  it('does not reconnect when scope object identity changes but values stay the same', async () => {
    let streamCallCount = 0
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, { signal, onEvent }) => {
        streamCallCount += 1
        onEvent({
          type: 'solution',
          playerId: 8,
          solutions: [
            {
              objectiveValue: 10,
              actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
            },
          ],
        })
        await new Promise<void>((resolve) => {
          signal?.addEventListener('abort', () => {
            resolve()
          })
        })
      }
    )

    const { result, rerender } = renderHook(
      ({ activeScope }) => useScoresInferenceByRow(tableData, activeScope, true),
      {
        initialProps: {
          activeScope: { ...scope },
        },
      }
    )

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.solutionCount).toBe(1)
    })
    expect(streamCallCount).toBe(1)

    rerender({ activeScope: { ...scope } })

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.solutionCount).toBe(1)
    })
    expect(streamCallCount).toBe(1)
  })

  describe('in-place table stream user scenarios', () => {
    it('UI refresh after all scores completed: recompute updates all rows on the same stream', async () => {
      const getStreamCallCount = longLivedTableStream([
        ({ onEvent }) => {
          emitComplete(onEvent, 8, 'Player 8 before recompute')
          emitComplete(onEvent, 9, 'Player 9 before recompute')
        },
        async ({ onEvent }) => {
          emitProgress(onEvent, 8)
          emitProgress(onEvent, 9)
          emitComplete(onEvent, 8, 'Player 8 after recompute')
          emitComplete(onEvent, 9, 'Player 9 after recompute')
        },
      ])

      const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

      await waitFor(() => {
        expect(result.current.inferenceByRow?.[0]?.summary).toBe('Player 8 after recompute')
        expect(result.current.inferenceByRow?.[1]?.summary).toBe('Player 9 after recompute')
      })
      expect(getStreamCallCount()).toBe(1)
    })

    it('UI refresh while some scores still computing: recompute updates via same stream', async () => {
      const getStreamCallCount = longLivedTableStream([
        ({ onEvent }) => {
          emitComplete(onEvent, 8, 'Player 8 before recompute')
          emitSolution(onEvent, 9)
        },
        async ({ onEvent }) => {
          emitProgress(onEvent, 8)
          emitComplete(onEvent, 8, 'Player 8 after recompute')
          emitProgress(onEvent, 9, 'tier_2')
        },
      ])

      const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

      await waitFor(() => {
        expect(result.current.inferenceByRow?.[0]?.summary).toBe('Player 8 after recompute')
        expect(result.current.inferenceByRow?.[1]?.summary).toBe('Searching (tier 2)')
        expect(result.current.inferenceByRow?.[1]?.isComplete).toBe(false)
      })
      expect(getStreamCallCount()).toBe(1)
    })

    it('mask change on player still computing: only the in-flight row resets on the same stream', async () => {
      const getStreamCallCount = longLivedTableStream([
        ({ onEvent }) => {
          emitSolution(onEvent, 8)
          emitComplete(onEvent, 9, 'Player 9 unchanged')
        },
        async ({ onEvent }) => {
          emitProgress(onEvent, 8)
          emitComplete(onEvent, 8, 'Player 8 after mask save')
        },
      ])

      const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

      await waitFor(() => {
        expect(result.current.inferenceByRow?.[0]?.summary).toBe('Player 8 after mask save')
        expect(result.current.inferenceByRow?.[1]?.summary).toBe('Player 9 unchanged')
      })
      expect(getStreamCallCount()).toBe(1)
    })

    it('mask change after score inference completed: only the edited row resets on the same stream', async () => {
      const getStreamCallCount = longLivedTableStream([
        ({ onEvent }) => {
          emitComplete(onEvent, 8, 'Player 8 before mask save')
          emitComplete(onEvent, 9, 'Player 9 unchanged')
        },
        async ({ onEvent }) => {
          emitProgress(onEvent, 8)
          emitComplete(onEvent, 8, 'Player 8 after mask save')
        },
      ])

      const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

      await waitFor(() => {
        expect(result.current.inferenceByRow?.[0]?.summary).toBe('Player 8 after mask save')
        expect(result.current.inferenceByRow?.[1]?.summary).toBe('Player 9 unchanged')
      })
      expect(getStreamCallCount()).toBe(1)
    })

    it('UI pause and resume: integrated row state on the table stream', async () => {
      let streamCallCount = 0
      let releasePausePhase: (() => void) | undefined
      let releaseResumePhase: (() => void) | undefined
      const pausePhaseReady = new Promise<void>((resolve) => {
        releasePausePhase = resolve
      })
      const resumePhaseReady = new Promise<void>((resolve) => {
        releaseResumePhase = resolve
      })

      vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
        async (_scope, _playerIds, handlers) => {
          streamCallCount += 1
          emitComplete(handlers.onEvent, 9, 'Player 9 complete')

          await pausePhaseReady
          emitGlobalPause(handlers.onEvent, true)

          await resumePhaseReady
          emitGlobalPause(handlers.onEvent, false)

          await new Promise<void>((resolve) => {
            handlers.signal?.addEventListener('abort', () => {
              resolve()
            })
          })
        }
      )

      const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

      await waitFor(() => {
        expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('pending')
        expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('success')
        expect(result.current.inferenceByRow?.[1]?.summary).toBe('Player 9 complete')
      })

      releasePausePhase!()
      await waitFor(() => {
        expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('paused')
        expect(result.current.inferenceByRow?.[0]?.summary).toBe('Build inference paused')
        expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('success')
      })

      releaseResumePhase!()
      await waitFor(() => {
        expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('pending')
        expect(result.current.inferenceByRow?.[0]?.summary).toBe('Build inference in progress')
        expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('success')
      })
      expect(streamCallCount).toBe(1)
    })
  })

  describe('stream lifecycle gaps (characterization)', () => {
    const threePlayerTable: TableDataResponse = {
      analyticId: 'scores',
      includeBuildInference: true,
      columns: ['Race (player)', 'Build inference'],
      rows: [['other', ''], ['cyborg', ''], ['colonies', '']],
      inferenceByRow: [{ playerId: 8 }, { playerId: 6 }, { playerId: 11 }],
    }

    it('keeps rows pending with empty diagnostics when the stream resolves without complete', async () => {
      vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
        async (_scope, _playerIds, handlers) => {
          emitComplete(handlers.onEvent, 8, 'Other player complete')
          emitProgress(handlers.onEvent, 6, 'early_game_bands')
          emitProgress(handlers.onEvent, 11, 'early_game_bands')
        }
      )

      const { result } = renderHook(() =>
        useScoresInferenceByRow(threePlayerTable, scope, true)
      )

      await waitFor(() => {
        expect(result.current.inferenceByRow?.[0]?.isComplete).toBe(true)
      })

      expect(result.current.inferenceByRow?.[1]).toMatchObject({
        playerId: 6,
        displayStatus: 'pending',
        isComplete: false,
        diagnostics: {},
        summary: 'Searching (early game bands)',
      })
      expect(result.current.inferenceByRow?.[2]).toMatchObject({
        playerId: 11,
        displayStatus: 'pending',
        isComplete: false,
        diagnostics: {},
        summary: 'Searching (early game bands)',
      })
    })

    it('remount after stream ends without terminal events can serve cached completes', async () => {
      let streamGeneration = 0

      vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
        async (_scope, _playerIds, handlers) => {
          streamGeneration += 1
          if (streamGeneration === 1) {
            emitComplete(handlers.onEvent, 8, 'Other player complete')
            emitProgress(handlers.onEvent, 6, 'early_game_bands')
            emitProgress(handlers.onEvent, 11, 'early_game_bands')
            return
          }
          emitComplete(handlers.onEvent, 6, 'Cyborg from cache', {
            turn: scope.turn,
            solver: { status: 'exact' },
          })
          emitComplete(handlers.onEvent, 11, 'Colonies from cache', {
            turn: scope.turn,
            solver: { status: 'exact' },
          })
        }
      )

      const { result, unmount } = renderHook(() =>
        useScoresInferenceByRow(threePlayerTable, scope, true)
      )

      await waitFor(() => {
        expect(result.current.inferenceByRow?.[0]?.isComplete).toBe(true)
        expect(result.current.inferenceByRow?.[1]?.isComplete).toBe(false)
      })

      unmount()

      const { result: remounted } = renderHook(() =>
        useScoresInferenceByRow(threePlayerTable, scope, true)
      )

      await waitFor(() => {
        expect(remounted.current.inferenceByRow?.[1]?.summary).toBe('Cyborg from cache')
        expect(remounted.current.inferenceByRow?.[2]?.summary).toBe('Colonies from cache')
      })
      expect(remounted.current.inferenceByRow?.[1]?.isComplete).toBe(true)
      expect(remounted.current.inferenceByRow?.[2]?.diagnostics).toMatchObject({
        turn: scope.turn,
        solver: { status: 'exact' },
      })
      expect(streamGeneration).toBe(2)
    })
  })
})
