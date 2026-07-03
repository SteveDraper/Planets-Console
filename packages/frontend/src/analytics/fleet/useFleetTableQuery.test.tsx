import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticShellScope, TableDataResponse } from '../../api/bff'
import {
  bumpScoresInferenceRevision,
  useScoresInferenceRevisionStore,
} from '../../stores/scoresInferenceRevision'
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

  it('does not refetch when scores inference revision bumps for the same scope', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    renderHook(({ activeScope, enabled }) => useFleetTableQuery(activeScope, enabled), {
      wrapper: createWrapper(client),
      initialProps: { activeScope: scope, enabled: true },
    })

    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(1)
    })

    act(() => {
      bumpScoresInferenceRevision(scope)
    })

    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(1)
    })
  })

  it('refetches after scores inference revision when the initial load returned 409', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchAnalyticTable)
      .mockRejectedValueOnce(new Error('409 — GET /bff/analytics/fleet/table'))
      .mockResolvedValueOnce({
        analyticId: 'fleet',
      } as unknown as TableDataResponse)

    const { result } = renderHook(
      ({ activeScope, enabled }) => useFleetTableQuery(activeScope, enabled),
      {
        wrapper: createWrapper(client),
        initialProps: { activeScope: scope, enabled: true },
      }
    )

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(1)
    })

    act(() => {
      bumpScoresInferenceRevision(scope)
    })

    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(2)
      expect(result.current.isSuccess).toBe(true)
    })
  })

  it('refetches after 409 when inference revision bumped during the in-flight fetch', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let resolveFirstFetch: (() => void) | undefined
    const firstFetchGate = new Promise<void>((resolve) => {
      resolveFirstFetch = resolve
    })

    vi.mocked(fetchAnalyticTable)
      .mockImplementationOnce(async () => {
        await firstFetchGate
        throw new Error('409 — GET /bff/analytics/fleet/table')
      })
      .mockResolvedValueOnce({
        analyticId: 'fleet',
      } as unknown as TableDataResponse)

    const { result } = renderHook(
      ({ activeScope, enabled }) => useFleetTableQuery(activeScope, enabled),
      {
        wrapper: createWrapper(client),
        initialProps: { activeScope: scope, enabled: true },
      }
    )

    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(1)
    })

    act(() => {
      bumpScoresInferenceRevision(scope)
    })

    await act(async () => {
      resolveFirstFetch?.()
    })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })

    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(2)
      expect(result.current.isSuccess).toBe(true)
    })
  })

  it('refetches once on initial 409 without waiting for another inference revision bump', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchAnalyticTable)
      .mockRejectedValueOnce(new Error('409 — GET /bff/analytics/fleet/table'))
      .mockResolvedValueOnce({
        analyticId: 'fleet',
      } as unknown as TableDataResponse)

    const { result } = renderHook(
      ({ activeScope, enabled }) => useFleetTableQuery(activeScope, enabled),
      {
        wrapper: createWrapper(client),
        initialProps: { activeScope: scope, enabled: true },
      }
    )

    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(2)
      expect(result.current.isSuccess).toBe(true)
    })
  })
})
