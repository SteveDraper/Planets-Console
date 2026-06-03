import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
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

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useScoresInferenceByRow', () => {
  it('returns pending while per-row inference requests are in flight', () => {
    vi.spyOn(bff, 'fetchScoresRowInference').mockImplementation(
      () => new Promise(() => {})
    )

    const { result } = renderHook(
      () => useScoresInferenceByRow(tableData, scope, true),
      { wrapper: createWrapper() }
    )

    expect(result.current).toHaveLength(2)
    expect(result.current?.[0]).toMatchObject({
      playerId: 8,
      displayStatus: 'pending',
    })
    expect(result.current?.[1]).toMatchObject({
      playerId: 9,
      displayStatus: 'pending',
    })
  })

  it('merges settled inference independently per player', async () => {
    vi.spyOn(bff, 'fetchScoresRowInference').mockImplementation(async (_scope, playerId) => {
      if (playerId === 8) {
        return {
          playerId: 8,
          displayStatus: 'success',
          status: 'exact',
          summary: 'Player 8 ok',
          solutionCount: 1,
          isComplete: true,
          solutions: [],
          diagnostics: { turn: 111 },
        }
      }
      throw new Error('502 player 9 failed')
    })

    const { result } = renderHook(
      () => useScoresInferenceByRow(tableData, scope, true),
      { wrapper: createWrapper() }
    )

    await waitFor(() => {
      expect(result.current?.[0]?.displayStatus).toBe('success')
      expect(result.current?.[1]?.displayStatus).toBe('failure')
    })
    expect(result.current?.[0]?.summary).toBe('Player 8 ok')
    expect(result.current?.[1]?.summary).toContain('502')
  })
})
