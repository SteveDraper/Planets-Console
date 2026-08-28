import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope, TableDataResponse } from '../../api/bff'
import { fetchAnalyticTable } from '../../api/bff'
import { scoresAnalyticTableQueryKey } from './api'
import { useBuildInferenceAvailable } from './useBuildInferenceAvailable'

vi.mock('../../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bff')>()
  return {
    ...actual,
    fetchAnalyticTable: vi.fn(),
  }
})

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

const scoresTableParams = { includeBuildInference: true } as const

function scoresTablePayload(
  buildInferenceAvailable?: boolean
): TableDataResponse {
  return {
    analyticId: 'scores',
    columns: ['Race / Player'],
    rows: [['The Birds (1)']],
    ...(buildInferenceAvailable === undefined ? {} : { buildInferenceAvailable }),
  }
}

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function renderAvailabilityHook(
  client: QueryClient,
  enabled = true
) {
  return renderHook(
    () => useBuildInferenceAvailable(scope, scoresTableParams, enabled),
    { wrapper: createWrapper(client) }
  )
}

describe('useBuildInferenceAvailable', () => {
  beforeEach(() => {
    vi.mocked(fetchAnalyticTable).mockReset()
  })

  it('does not claim available while the shared scores table query is in flight', () => {
    vi.mocked(fetchAnalyticTable).mockImplementation(() => new Promise(() => {}))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    const { result } = renderAvailabilityHook(client)

    expect(result.current).toBeUndefined()
    expect(fetchAnalyticTable).toHaveBeenCalledWith('scores', scope, scoresTableParams)
  })

  it('returns false when the payload says build inference is unavailable', async () => {
    vi.mocked(fetchAnalyticTable).mockResolvedValue(scoresTablePayload(false))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    const { result } = renderAvailabilityHook(client)

    await waitFor(() => {
      expect(result.current).toBe(false)
    })
  })

  it('returns true when the payload says build inference is available', async () => {
    vi.mocked(fetchAnalyticTable).mockResolvedValue(scoresTablePayload(true))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    const { result } = renderAvailabilityHook(client)

    await waitFor(() => {
      expect(result.current).toBe(true)
    })
  })

  it('treats a successful payload that omits the flag as available', async () => {
    vi.mocked(fetchAnalyticTable).mockResolvedValue(scoresTablePayload())
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    const { result } = renderAvailabilityHook(client)

    await waitFor(() => {
      expect(result.current).toBe(true)
    })
  })

  it('shares the TableTile scores table query key so React Query dedupes', async () => {
    vi.mocked(fetchAnalyticTable).mockResolvedValue(scoresTablePayload(true))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = createWrapper(client)

    renderHook(
      () => useBuildInferenceAvailable(scope, scoresTableParams, true),
      { wrapper }
    )
    renderHook(
      () => useBuildInferenceAvailable(scope, scoresTableParams, true),
      { wrapper }
    )

    await waitFor(() => {
      expect(fetchAnalyticTable).toHaveBeenCalledTimes(1)
    })
    expect(scoresAnalyticTableQueryKey(scope, scoresTableParams)).toEqual([
      'analytic',
      'scores',
      'table',
      scope,
      true,
    ])
  })

  it('does not fetch when disabled', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    const { result } = renderAvailabilityHook(client, false)

    expect(result.current).toBeUndefined()
    expect(fetchAnalyticTable).not.toHaveBeenCalled()
  })
})
