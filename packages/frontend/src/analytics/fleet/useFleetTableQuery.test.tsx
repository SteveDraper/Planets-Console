import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticShellScope, TableDataResponse } from '../../api/bff'
import {
  bumpScoresInferenceRevision,
  useScoresInferenceRevisionStore,
} from '../../shell/scoresInferenceRevision'
import { useFleetTableQuery } from './useFleetTableQuery'

vi.mock('../../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bff')>()
  return {
    ...actual,
    fetchAnalyticTable: vi.fn(),
  }
})

import { fetchAnalyticTable } from '../../api/bff'

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 3,
  perspective: 1,
}

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useFleetTableQuery', () => {
  beforeEach(() => {
    useScoresInferenceRevisionStore.getState().resetRevisions()
    vi.mocked(fetchAnalyticTable).mockReset()
    vi.mocked(fetchAnalyticTable).mockResolvedValue({
      analyticId: 'fleet',
    } as unknown as TableDataResponse)
  })

  it('refetches when scores inference revision bumps for the same scope', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    const { rerender } = renderHook(
      ({ activeScope, enabled }) => useFleetTableQuery(activeScope, enabled),
      {
        wrapper: createWrapper(client),
        initialProps: { activeScope: scope, enabled: true },
      }
    )

    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(1)
    })

    bumpScoresInferenceRevision(scope)
    rerender({ activeScope: scope, enabled: true })

    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(2)
    })
  })
})
