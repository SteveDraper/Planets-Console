import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import {
  defaultConnectionsParams,
  defaultStellarCartography,
  sampleAnalytics,
  sampleScope,
} from './mapAnalyticQueryTestFixtures'
import { useMapAnalyticQueries, type UseMapAnalyticQueriesInput } from './useMapAnalyticQueries'

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

import { fetchAnalyticMap } from '../api/bff'
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
    futureTurnOffset: 0,
    stellarCartography: defaultStellarCartography,
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
        stellarCartography: {
          ...defaultStellarCartography,
          wormholeDisplayMode: 'always',
          settingsGates: {
            ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
            wormholes: true,
          },
        },
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

  it('recombines when stellar cartography visibility changes', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchAnalyticMap).mockImplementation(async (analyticId) => {
      if (analyticId === 'base-map') {
        return { analyticId: 'base-map', nodes: [], edges: [] }
      }
      if (analyticId === 'connections') {
        return { analyticId: 'connections', nodes: [], edges: [], routes: [] }
      }
      if (analyticId === 'stellar-cartography') {
        return {
          analyticId: 'stellar-cartography',
          nodes: [],
          edges: [],
          overlayCircles: [
            {
              layer: 'nebulae',
              id: 'neb-1',
              x: 1,
              y: 2,
              radius: 3,
            },
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
        initialProps: defaultHookInput({
          enabledAnalyticIds: ['connections', 'stellar-cartography'],
          stellarCartography: {
            ...defaultStellarCartography,
            settingsGates: {
              ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
              nebulae: true,
            },
          },
        }),
      }
    )

    await waitFor(() => {
      expect(result.current.combined.overlayCircles.length).toBeGreaterThan(0)
    })

    rerender(
      defaultHookInput({
        enabledAnalyticIds: ['connections', 'stellar-cartography'],
        stellarCartography: {
          ...defaultStellarCartography,
          layerVisibility: {
            ...defaultStellarCartography.layerVisibility,
            nebulae: false,
          },
          settingsGates: {
            ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
            nebulae: true,
          },
        },
      })
    )

    await waitFor(() => {
      expect(result.current.combined.overlayCircles).toHaveLength(0)
    })
  })

  it('recombines when futureTurnOffset changes with stellar cartography enabled', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchAnalyticMap).mockImplementation(async (analyticId) => {
      if (analyticId === 'base-map') {
        return { analyticId: 'base-map', nodes: [], edges: [] }
      }
      if (analyticId === 'connections') {
        return { analyticId: 'connections', nodes: [], edges: [], routes: [] }
      }
      if (analyticId === 'stellar-cartography') {
        return {
          analyticId: 'stellar-cartography',
          nodes: [],
          edges: [],
          overlayCircles: [
            {
              layer: 'ion-storms',
              id: 'storm-1',
              x: 100,
              y: 200,
              radius: 30,
              class: 2,
              heading: 0,
              warp: 5,
            },
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
        initialProps: defaultHookInput({
          enabledAnalyticIds: ['connections', 'stellar-cartography'],
          futureTurnOffset: 0,
          stellarCartography: {
            ...defaultStellarCartography,
            settingsGates: {
              ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
              ionStorms: true,
            },
          },
        }),
      }
    )

    await waitFor(() => {
      expect(result.current.combined.overlayCircles).toHaveLength(1)
    })
    const circleAtZero = result.current.combined.overlayCircles[0]

    rerender(
      defaultHookInput({
        enabledAnalyticIds: ['connections', 'stellar-cartography'],
        futureTurnOffset: 2,
        stellarCartography: {
          ...defaultStellarCartography,
          settingsGates: {
            ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
            ionStorms: true,
          },
        },
      })
    )

    await waitFor(() => {
      expect(result.current.combined.overlayCircles[0]?.y).toBe(250)
      expect(circleAtZero?.y).toBe(200)
    })
    expect(vi.mocked(combineMapData).mock.calls.at(-1)?.[2]).toMatchObject({
      futureTurnOffset: 2,
    })
  })
})
