import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import {
  defaultConnectionsParams,
  sampleAnalytics,
  sampleScope,
} from './mapAnalyticQueryTestFixtures'
import { useMapAnalyticQueries, type UseMapAnalyticQueriesInput } from './useMapAnalyticQueries'
import { HOMEWORLD_LOCATOR_ANALYTIC_ID } from '../analytics/mapAnalyticIds'
import type { AnalyticItem } from '../api/bff'

vi.mock('../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/bff')>()
  return {
    ...actual,
    fetchAnalyticMap: vi.fn().mockResolvedValue({
      analyticId: 'base-map',
      nodes: [{ id: 'base-map:1', label: 'A', x: 1, y: 2 }],
      edges: [],
    }),
  }
})

vi.mock('../analytics/homeworld-locator/api', () => ({
  fetchHomeworldLocatorMap: vi.fn(),
  fetchHomeworldLocatorTable: vi.fn(),
  postHomeworldLocatorAssertion: vi.fn(),
  postHomeworldLocatorRefresh: vi.fn(),
}))

import { fetchAnalyticMap } from '../api/bff'
import { fetchHomeworldLocatorMap } from '../analytics/homeworld-locator/api'
import { combineMapData } from '../analytics/mapLayers'

vi.mock('../analytics/mapLayers', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../analytics/mapLayers')>()
  return {
    ...actual,
    combineMapData: vi.fn(actual.combineMapData),
  }
})

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function defaultHookInput(
  overrides: Partial<UseMapAnalyticQueriesInput> = {}
): UseMapAnalyticQueriesInput {
  return {
    enabledAnalyticIds: ['connections'],
    analytics: sampleAnalytics,
    analyticScope: sampleScope,
    analyticFetchEnabled: true,
    connectionsMapParams: defaultConnectionsParams,
    ...overrides,
  }
}

describe('useMapAnalyticQueries', () => {
  it('combines map query results when data arrives', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchAnalyticMap).mockClear()
    vi.mocked(combineMapData).mockClear()

    const { result } = renderHook(() => useMapAnalyticQueries(defaultHookInput()), {
      wrapper: createWrapper(client),
    })

    await waitFor(() => {
      expect(result.current.hasAnyData).toBe(true)
    })

    expect(combineMapData).toHaveBeenCalled()
    expect(result.current.mapIds).toEqual(['base-map', 'connections'])
    expect(result.current.combined.nodes.length).toBeGreaterThan(0)
  })

  it('recombines when connections flare mode changes', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchAnalyticMap).mockImplementation(async (analyticId) => {
      if (analyticId === 'base-map') {
        return {
          analyticId: 'base-map',
          nodes: [
            { id: 'p1', label: 'p1', x: 10, y: 20 },
            { id: 'p2', label: 'p2', x: 30, y: 40 },
            { id: 'p3', label: 'p3', x: 50, y: 60 },
          ],
          edges: [],
        }
      }
      if (analyticId === 'connections') {
        return {
          analyticId: 'connections',
          nodes: [],
          edges: [],
          routes: [
            { fromPlanetId: 1, toPlanetId: 2, viaFlare: false },
            { fromPlanetId: 2, toPlanetId: 3, viaFlare: true },
          ],
        }
      }
      throw new Error(`unexpected analytic ${analyticId}`)
    })
    vi.mocked(combineMapData).mockClear()

    const { result, rerender } = renderHook(
      (input: UseMapAnalyticQueriesInput) => useMapAnalyticQueries(input),
      {
        wrapper: createWrapper(client),
        initialProps: defaultHookInput(),
      }
    )

    await waitFor(() => {
      expect(result.current.hasAnyData).toBe(true)
    })
    const edgesOffFlare = result.current.combined.edges

    rerender(
      defaultHookInput({
        connectionsMapParams: {
          ...defaultConnectionsParams,
          flareMode: 'only',
        },
      })
    )

    await waitFor(() => {
      expect(result.current.combined.edges).not.toEqual(edgesOffFlare)
    })
    expect(vi.mocked(combineMapData).mock.calls.at(-1)?.[2]).toMatchObject({
      liveConnectionsParams: expect.objectContaining({ flareMode: 'only' }),
    })
  })

  it('recombines when enabled map analytics change', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchAnalyticMap).mockImplementation(async (analyticId) => {
      if (analyticId === 'base-map') {
        return {
          analyticId: 'base-map',
          nodes: [{ id: 'p1', label: 'p1', x: 1, y: 2 }],
          edges: [],
        }
      }
      if (analyticId === 'connections') {
        return { analyticId: 'connections', nodes: [], edges: [], routes: [] }
      }
      if (analyticId === 'stellar-cartography') {
        return {
          analyticId: 'stellar-cartography',
          nodes: [{ id: 'wh-1', label: '', x: 5, y: 6 }],
          edges: [],
          overlayCircles: [],
        }
      }
      throw new Error(`unexpected analytic ${analyticId}`)
    })
    vi.mocked(combineMapData).mockClear()

    const { result, rerender } = renderHook(
      (input: UseMapAnalyticQueriesInput) => useMapAnalyticQueries(input),
      {
        wrapper: createWrapper(client),
        initialProps: defaultHookInput({ enabledAnalyticIds: ['connections'] }),
      }
    )

    await waitFor(() => {
      expect(result.current.mapIds).toEqual(['base-map', 'connections'])
    })

    rerender(
      defaultHookInput({
        enabledAnalyticIds: ['connections', 'stellar-cartography'],
      })
    )

    await waitFor(() => {
      expect(result.current.mapIds).toEqual([
        'base-map',
        'connections',
        'stellar-cartography',
      ])
      expect(result.current.combined.wormholeUnknownEntrances).toEqual([{ x: 5, y: 6 }])
    })
    expect(vi.mocked(combineMapData).mock.calls.at(-1)?.[0]).toEqual([
      'base-map',
      'connections',
      'stellar-cartography',
    ])
  })

  it('passes null liveConnectionsParams when fetch is disabled', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(combineMapData).mockClear()

    renderHook(
      () =>
        useMapAnalyticQueries(
          defaultHookInput({
            analyticFetchEnabled: false,
          })
        ),
      { wrapper: createWrapper(client) }
    )

    await waitFor(() => {
      expect(combineMapData).toHaveBeenCalled()
    })
    expect(vi.mocked(combineMapData).mock.calls.at(-1)?.[2]).toMatchObject({
      liveConnectionsParams: null,
    })
  })

  it('recombines when query data changes at the same array lengths', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let baseMapY = 10
    vi.mocked(fetchAnalyticMap).mockImplementation(async (analyticId) => {
      if (analyticId === 'base-map') {
        return {
          analyticId: 'base-map',
          nodes: [{ id: 'p1', label: 'p1', x: 1, y: baseMapY }],
          edges: [],
        }
      }
      if (analyticId === 'connections') {
        return { analyticId: 'connections', nodes: [], edges: [], routes: [] }
      }
      throw new Error(`unexpected analytic ${analyticId}`)
    })
    vi.mocked(combineMapData).mockClear()

    const { result } = renderHook(() => useMapAnalyticQueries(defaultHookInput()), {
      wrapper: createWrapper(client),
    })

    await waitFor(() => {
      expect(result.current.combined.nodes[0]?.y).toBe(10)
    })

    baseMapY = 99
    await client.invalidateQueries({ queryKey: ['analytic', 'base-map', 'map'] })

    await waitFor(() => {
      expect(result.current.combined.nodes[0]?.y).toBe(99)
    })
  })

  it('excludes errored layer last-good data from combined while keeping healthy layers', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let stellarShouldFail = false
    vi.mocked(fetchAnalyticMap).mockImplementation(async (analyticId) => {
      if (analyticId === 'base-map') {
        return {
          analyticId: 'base-map',
          nodes: [{ id: 'p1', label: 'p1', x: 1, y: 2 }],
          edges: [],
        }
      }
      if (analyticId === 'connections') {
        return { analyticId: 'connections', nodes: [], edges: [], routes: [] }
      }
      if (analyticId === 'stellar-cartography') {
        if (stellarShouldFail) {
          throw new Error('stellar cartography map failed')
        }
        return {
          analyticId: 'stellar-cartography',
          nodes: [{ id: 'wh-1', label: '', x: 5, y: 6 }],
          edges: [],
          overlayCircles: [],
        }
      }
      throw new Error(`unexpected analytic ${analyticId}`)
    })

    const { result } = renderHook(
      () =>
        useMapAnalyticQueries(
          defaultHookInput({
            enabledAnalyticIds: ['connections', 'stellar-cartography'],
          })
        ),
      { wrapper: createWrapper(client) }
    )

    await waitFor(() => {
      expect(result.current.combined.wormholeUnknownEntrances).toEqual([{ x: 5, y: 6 }])
    })
    expect(result.current.hasError).toBe(false)

    stellarShouldFail = true
    await client.invalidateQueries({ queryKey: ['analytic', 'stellar-cartography', 'map'] })

    await waitFor(() => {
      expect(result.current.hasError).toBe(true)
    })

    const failedLayer = result.current.mapQueries.find((q) => q.isError)
    expect(failedLayer?.data).toBeDefined()
    expect(failedLayer?.data?.analyticId).toBe('stellar-cartography')
    expect(result.current.combined.wormholeUnknownEntrances).toEqual([])
    expect(result.current.combined.nodes.length).toBeGreaterThan(0)
    expect(result.current.hasAnyData).toBe(true)
    expect(String(result.current.mapError)).toMatch(/stellar cartography map failed/i)
  })

  describe('homeworldMapLayerSucceeded', () => {
    const analyticsWithHomeworld: AnalyticItem[] = [
      ...sampleAnalytics,
      {
        id: HOMEWORLD_LOCATOR_ANALYTIC_ID,
        name: 'Homeworld locator',
        supportsTable: true,
        supportsMap: true,
        type: 'selectable',
      },
    ]

    it('is false when homeworld is not in the fetch set', async () => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      const { result } = renderHook(() => useMapAnalyticQueries(defaultHookInput()), {
        wrapper: createWrapper(client),
      })

      await waitFor(() => {
        expect(result.current.hasAnyData).toBe(true)
      })
      expect(result.current.homeworldMapLayerSucceeded).toBe(false)
    })

    it('is true after homeworld map success (including empty overlays)', async () => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      vi.mocked(fetchAnalyticMap).mockImplementation(async (analyticId) => {
        if (analyticId === 'base-map') {
          return {
            analyticId: 'base-map',
            nodes: [{ id: 'p1', label: 'p1', x: 1, y: 2 }],
            edges: [],
          }
        }
        if (analyticId === 'connections') {
          return { analyticId: 'connections', nodes: [], edges: [], routes: [] }
        }
        throw new Error(`unexpected analytic ${analyticId}`)
      })
      vi.mocked(fetchHomeworldLocatorMap).mockResolvedValue({
        analyticId: HOMEWORLD_LOCATOR_ANALYTIC_ID,
        available: true,
        baselineDegraded: false,
        regionOverlays: [],
        markers: [],
      })

      const { result } = renderHook(
        () =>
          useMapAnalyticQueries(
            defaultHookInput({
              enabledAnalyticIds: ['connections', HOMEWORLD_LOCATOR_ANALYTIC_ID],
              analytics: analyticsWithHomeworld,
            })
          ),
        { wrapper: createWrapper(client) }
      )

      await waitFor(() => {
        expect(result.current.pending).toBe(false)
        expect(result.current.homeworldMapLayerSucceeded).toBe(true)
      })
      expect(result.current.hasError).toBe(false)
    })

    it('is false when the homeworld map layer errors (failure-empty)', async () => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      vi.mocked(fetchAnalyticMap).mockImplementation(async (analyticId) => {
        if (analyticId === 'base-map') {
          return {
            analyticId: 'base-map',
            nodes: [{ id: 'p1', label: 'p1', x: 1, y: 2 }],
            edges: [],
          }
        }
        if (analyticId === 'connections') {
          return { analyticId: 'connections', nodes: [], edges: [], routes: [] }
        }
        throw new Error(`unexpected analytic ${analyticId}`)
      })
      vi.mocked(fetchHomeworldLocatorMap).mockRejectedValue(
        new Error('homeworld turn gap')
      )

      const { result } = renderHook(
        () =>
          useMapAnalyticQueries(
            defaultHookInput({
              enabledAnalyticIds: ['connections', HOMEWORLD_LOCATOR_ANALYTIC_ID],
              analytics: analyticsWithHomeworld,
            })
          ),
        { wrapper: createWrapper(client) }
      )

      await waitFor(() => {
        expect(result.current.pending).toBe(false)
        expect(result.current.hasError).toBe(true)
      })
      expect(result.current.homeworldMapLayerSucceeded).toBe(false)
      expect(result.current.combined.regionOverlays).toEqual([])
    })
  })
})
