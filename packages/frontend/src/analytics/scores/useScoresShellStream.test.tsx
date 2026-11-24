import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as bff from '../../api/bff'
import { useScoresTablePreferencesStore } from '../../stores/scoresTablePreferences'
import {
  delay,
  emitComplete,
  emitGlobalPause,
  scope,
  tableData,
} from './scoresInferenceStreamTestFixtures'
import { useScoresShellStream } from './useScoresShellStream'

function renderScoresShellStream() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderHook(() => useScoresShellStream(scope, true), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}

describe('useScoresShellStream table pause', () => {
  beforeEach(() => {
    vi.spyOn(bff, 'fetchAnalyticTable').mockResolvedValue(tableData)
    useScoresTablePreferencesStore.setState({
      scoresTableParams: { includeBuildInference: true },
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

    const { result } = renderScoresShellStream()

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

    const { result } = renderScoresShellStream()

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
          displayStatus: 'success',
          summary: 'Player 8 ok',
          solutionCount: 1,
          isComplete: true,
        })
        handlers.onEvent({ type: 'globalPause', paused: true })
        await new Promise(() => {})
      }
    )

    const { result } = renderScoresShellStream()

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('success')
      expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('paused')
    })
  })

  it('keeps a row paused when its work is accepted while the table is paused', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'stored_row',
          playerId: 8,
          status: 'exact',
          displayStatus: 'success',
          summary: 'Stored build',
          solutionCount: 0,
          isComplete: true,
          evidenceGeneration: 1,
          evidenceMark: 2,
          solutions: [],
        })
        handlers.onEvent({ type: 'globalPause', paused: true })
        await delay(0)
        handlers.onEvent({ type: 'work_accepted', playerId: 8 })
        handlers.onEvent({ type: 'work_accepted', playerId: 9 })
        await new Promise(() => {})
      }
    )

    const { result } = renderScoresShellStream()

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.isComplete).toBe(false)
      expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('paused')
      expect(result.current.inferenceByRow?.[1]?.displayStatus).toBe('paused')
    })
    expect(result.current.inferenceByRow?.[0]?.summary).toBe('Build inference paused')
  })

  it('shows accepted work as in progress once the table resumes', async () => {
    vi.spyOn(bff, 'fetchScoresTableInferenceStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({ type: 'globalPause', paused: true })
        handlers.onEvent({ type: 'work_accepted', playerId: 8 })
        await delay(0)
        handlers.onEvent({ type: 'globalPause', paused: false })
        await new Promise(() => {})
      }
    )

    const { result } = renderScoresShellStream()

    await waitFor(() => {
      expect(result.current.inferenceByRow?.[0]?.displayStatus).toBe('pending')
    })
    expect(result.current.inferenceByRow?.[0]?.summary).toBe('Build inference in progress')
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

    const { result } = renderScoresShellStream()

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
