import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope, TableDataResponse } from '../../api/bff'
import * as bff from '../../api/bff'
import { useScoresInferenceByRow } from './useScoresInferenceByRow'

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

  it('refreshInference restarts the table stream and applies new row results', async () => {
    let streamCallCount = 0
    let releaseSecondStream: (() => void) | null = null

    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, { signal, onEvent }) => {
        streamCallCount += 1
        if (streamCallCount === 1) {
          onEvent({
            type: 'complete',
            playerId: 8,
            status: 'exact',
            summary: 'Player 8 before mask save',
            solutionCount: 1,
            isComplete: true,
          })
          await new Promise<void>((resolve) => {
            signal?.addEventListener('abort', () => {
              resolve()
            })
          })
          return
        }
        await new Promise<void>((resolve) => {
          releaseSecondStream = resolve
        })
        onEvent({
          type: 'complete',
          playerId: 8,
          status: 'exact',
          summary: 'Player 8 after mask save',
          solutionCount: 1,
          isComplete: true,
        })
        onEvent({
          type: 'complete',
          playerId: 9,
          status: 'exact',
          summary: 'Player 9 after mask save',
          solutionCount: 1,
          isComplete: true,
        })
      }
    )

    const { result } = renderHook(() => useScoresInferenceByRow(tableData, scope, true))

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.summary).toBe('Player 8 before mask save')
    })

    result.current.refreshInference()

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('pending')
      expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('pending')
      expect(streamCallCount).toBe(2)
    })

    releaseSecondStream!()

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.summary).toBe('Player 8 after mask save')
      expect(result.current.inferenceByRow?.[1]?.summary).toBe('Player 9 after mask save')
      expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('success')
      expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('success')
    })
  })
})
