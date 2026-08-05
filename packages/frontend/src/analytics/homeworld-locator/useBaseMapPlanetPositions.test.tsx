import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchAnalyticMap } from '../../api/bff'
import { sampleScope } from '../../lib/mapAnalyticQueryTestFixtures'
import { useBaseMapPlanetPositions } from './useBaseMapPlanetPositions'

vi.mock('../../api/bff', async () => {
  const actual = await vi.importActual<typeof import('../../api/bff')>('../../api/bff')
  return {
    ...actual,
    fetchAnalyticMap: vi.fn(),
  }
})

function renderPositionsHook(fetchEnabled: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderHook(
    () =>
      useBaseMapPlanetPositions({
        analyticScope: sampleScope,
        fetchEnabled,
      }),
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    }
  )
}

describe('useBaseMapPlanetPositions', () => {
  beforeEach(() => {
    vi.mocked(fetchAnalyticMap).mockReset()
  })

  it('uses the shell base-map query key (planet-v2) and maps nodes to positions', async () => {
    vi.mocked(fetchAnalyticMap).mockResolvedValue({
      analyticId: 'base-map',
      nodes: [{ id: 'p12', label: 'p12', x: 50, y: 60, planet: { id: 12 } }],
      edges: [],
    })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(
      () =>
        useBaseMapPlanetPositions({
          analyticScope: sampleScope,
          fetchEnabled: true,
        }),
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      }
    )

    await waitFor(() => {
      expect(result.current.positionsReady).toBe(true)
    })

    expect(fetchAnalyticMap).toHaveBeenCalledWith('base-map', sampleScope, undefined)
    expect(result.current.planetPositions.get(12)).toEqual({ x: 50, y: 60 })
    expect(result.current.positionsError).toBeNull()
    const keys = client
      .getQueryCache()
      .getAll()
      .map((entry) => entry.queryKey)
    expect(keys).toContainEqual(['analytic', 'base-map', 'map', sampleScope, 'planet-v2'])
  })

  it('does not fetch when disabled', async () => {
    const { result } = renderPositionsHook(false)
    expect(result.current.positionsReady).toBe(false)
    expect(fetchAnalyticMap).not.toHaveBeenCalled()
  })

  it('surfaces fetch errors', async () => {
    vi.mocked(fetchAnalyticMap).mockRejectedValue(new Error('base map unavailable'))

    const { result } = renderPositionsHook(true)

    await waitFor(() => {
      expect(result.current.positionsError).toBeTruthy()
    })
    expect(result.current.positionsReady).toBe(false)
    expect(errorMessage(result.current.positionsError)).toMatch(/base map unavailable/i)
  })
})

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
