import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { HOMEWORLD_SECTOR_KIND } from './homeworldSectorIndex'
import { fetchHomeworldLocatorMap } from './api'
import { homeworldLocatorMapQueryKey } from './mapAnalytic'
import { useHomeworldLocatorMapOverlays } from './useHomeworldLocatorMapOverlays'

vi.mock('./api', () => ({
  fetchHomeworldLocatorMap: vi.fn(),
  fetchHomeworldLocatorTable: vi.fn(),
  postHomeworldLocatorAssertion: vi.fn(),
  postHomeworldLocatorRefresh: vi.fn(),
}))

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 5,
  perspective: 1,
  username: 'alice',
}

const SECTOR_OVERLAY: MapRegionOverlay = {
  kind: HOMEWORLD_SECTOR_KIND,
  id: 'homeworld-sector-0',
  fillColor: '#f97316',
  fillOpacity: 0,
  isPinned: true,
  geometry: {
    type: 'boundary',
    vertices: [
      { x: 0, y: 0 },
      { x: 1, y: 0 },
      { x: 1, y: 1 },
      { x: 0, y: 1 },
    ],
    edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }, { type: 'line' }],
  },
}

function renderOverlaysHook(fetchEnabled: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    client,
    ...renderHook(
      () =>
        useHomeworldLocatorMapOverlays({
          analyticScope: scope,
          fetchEnabled,
        }),
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      }
    ),
  }
}

describe('useHomeworldLocatorMapOverlays', () => {
  beforeEach(() => {
    vi.mocked(fetchHomeworldLocatorMap).mockReset()
  })

  it('uses the homeworld map registration query key and returns sector overlays', async () => {
    vi.mocked(fetchHomeworldLocatorMap).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      regionOverlays: [SECTOR_OVERLAY],
      markers: [],
    })

    const { client, result } = renderOverlaysHook(true)

    await waitFor(() => {
      expect(result.current.overlaysReady).toBe(true)
    })

    expect(fetchHomeworldLocatorMap).toHaveBeenCalledWith(scope)
    expect(result.current.overlays).toEqual([SECTOR_OVERLAY])
    expect(result.current.overlaysError).toBeNull()
    const keys = client
      .getQueryCache()
      .getAll()
      .map((entry) => entry.queryKey)
    expect(keys).toContainEqual([...homeworldLocatorMapQueryKey(scope)])
  })

  it('does not fetch when disabled', () => {
    const { result } = renderOverlaysHook(false)
    expect(result.current.overlaysReady).toBe(false)
    expect(result.current.overlays).toEqual([])
    expect(fetchHomeworldLocatorMap).not.toHaveBeenCalled()
  })

  it('surfaces fetch errors', async () => {
    vi.mocked(fetchHomeworldLocatorMap).mockRejectedValue(new Error('homeworld map unavailable'))

    const { result } = renderOverlaysHook(true)

    await waitFor(() => {
      expect(result.current.overlaysError).toBeTruthy()
    })
    expect(result.current.overlaysReady).toBe(false)
    expect(errorMessage(result.current.overlaysError)).toMatch(/homeworld map unavailable/i)
  })
})

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
