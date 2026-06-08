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
          solution: {
            objectiveValue: 10,
            actions: [{ actionId: 'a1', label: 'Build fighter', count: 1 }],
          },
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
})
