import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticItem, AnalyticShellScope, ConnectionsMapParams } from '../api/bff'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import {
  combinedMapDataMemoDeps,
  connectionsMapQueryKey,
  enabledMapAnalyticIds,
  mapIdsToFetch,
  mapQueriesStateSignature,
  useMapAnalyticQueries,
} from './useMapAnalyticQueries'

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

const defaultConnectionsParams: ConnectionsMapParams = {
  warpSpeed: 9,
  gravitonicMovement: false,
  flareMode: 'off',
  flareDepth: 2,
}

const sampleAnalytics: AnalyticItem[] = [
  { id: 'base-map', name: 'Base', supportsTable: false, supportsMap: true, type: 'base' },
  { id: 'connections', name: 'Connections', supportsTable: true, supportsMap: true, type: 'selectable' },
  {
    id: 'stellar-cartography',
    name: 'Stellar Cartography',
    supportsTable: false,
    supportsMap: true,
    type: 'selectable',
  },
]

const sampleScope: AnalyticShellScope = {
  gameId: '628580',
  turn: 5,
  perspective: 1,
}

const defaultStellarCartography = {
  layerVisibility: {
    'debris-disks': true,
    nebulae: true,
    'ion-storms': true,
    'black-holes': true,
  },
  settingsGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
  wormholeDisplayMode: 'off' as const,
  starClusterDisplayMode: 'off' as const,
  neutronClusterDisplayMode: 'off' as const,
}

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('connectionsMapQueryKey', () => {
  it.each([
    {
      label: 'idle placeholders when scope is null',
      scope: null,
      params: defaultConnectionsParams,
      expected: [
        'analytic',
        'connections',
        'map',
        'idle',
        0,
        0,
        9,
        false,
        'off',
        2,
      ],
    },
    {
      label: 'scope fields when scope is set',
      scope: sampleScope,
      params: defaultConnectionsParams,
      expected: [
        'analytic',
        'connections',
        'map',
        '628580',
        5,
        1,
        9,
        false,
        'off',
        2,
      ],
    },
    {
      label: 'connection params when scope is null',
      scope: null,
      params: {
        warpSpeed: 6,
        gravitonicMovement: true,
        flareMode: 'include' as const,
        flareDepth: 3 as const,
      },
      expected: ['analytic', 'connections', 'map', 'idle', 0, 0, 6, true, 'include', 3],
    },
  ])('$label', ({ scope, params, expected }) => {
    expect(connectionsMapQueryKey(scope, params)).toEqual(expected)
  })
})

describe('enabledMapAnalyticIds and mapIdsToFetch', () => {
  it('includes base map first and skips duplicate base id in enabled list', () => {
    const enabled = enabledMapAnalyticIds(
      ['connections', 'base-map', 'stellar-cartography'],
      sampleAnalytics
    )
    expect(enabled).toEqual(['connections', 'stellar-cartography'])
    expect(mapIdsToFetch(sampleAnalytics, enabled)).toEqual([
      'base-map',
      'connections',
      'stellar-cartography',
    ])
  })
})

describe('mapQueriesStateSignature', () => {
  it('joins query snapshots with pipe separators', () => {
    expect(
      mapQueriesStateSignature([
        { dataUpdatedAt: 1, fetchStatus: 'idle', status: 'success' },
        { dataUpdatedAt: 2, fetchStatus: 'fetching', status: 'pending' },
      ])
    ).toBe('1:idle:success|2:fetching:pending')
  })
})

describe('combinedMapDataMemoDeps', () => {
  const baseInput = {
    mapIdsKey: 'base-map\0connections',
    mapQueriesStateSignature: '1:idle:success',
    liveConnectionsParams: defaultConnectionsParams,
    analyticFetchEnabled: true,
    includesStellarCartography: false,
    connectionsMapParams: defaultConnectionsParams,
    futureTurnOffset: 0,
    stellarCartography: defaultStellarCartography,
  }

  it.each([
    {
      field: 'mapIdsKey',
      mutate: (input: typeof baseInput) => ({ ...input, mapIdsKey: 'base-map' }),
    },
    {
      field: 'mapQueriesStateSignature',
      mutate: (input: typeof baseInput) => ({
        ...input,
        mapQueriesStateSignature: '2:fetching:pending',
      }),
    },
    {
      field: 'liveConnectionsParams',
      mutate: (input: typeof baseInput) => ({ ...input, liveConnectionsParams: null }),
    },
    {
      field: 'connectionsMapParams.flareMode',
      mutate: (input: typeof baseInput) => ({
        ...input,
        connectionsMapParams: { ...input.connectionsMapParams, flareMode: 'include' as const },
      }),
    },
    {
      field: 'futureTurnOffset',
      mutate: (input: typeof baseInput) => ({ ...input, futureTurnOffset: 2 }),
    },
    {
      field: 'stellarCartography.layerVisibility',
      mutate: (input: typeof baseInput) => ({
        ...input,
        stellarCartography: {
          ...input.stellarCartography,
          layerVisibility: { ...input.stellarCartography.layerVisibility, nebulae: false },
        },
      }),
    },
    {
      field: 'includesStellarCartography',
      mutate: (input: typeof baseInput) => ({ ...input, includesStellarCartography: true }),
    },
  ])('changes when $field changes', ({ mutate }) => {
    const before = combinedMapDataMemoDeps(baseInput)
    const after = combinedMapDataMemoDeps(mutate(baseInput))
    expect(after).not.toEqual(before)
  })

  it('is stable when unrelated object identity changes but values match', () => {
    const first = combinedMapDataMemoDeps(baseInput)
    const second = combinedMapDataMemoDeps({
      ...baseInput,
      connectionsMapParams: { ...defaultConnectionsParams },
      stellarCartography: {
        ...defaultStellarCartography,
        settingsGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
      },
    })
    expect(second).toEqual(first)
  })
})

describe('useMapAnalyticQueries', () => {
  it('registers idle connections query key when scope is null', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchAnalyticMap).mockClear()
    vi.mocked(combineMapData).mockClear()

    renderHook(
      () =>
        useMapAnalyticQueries({
          viewMode: 'map',
          enabledAnalyticIds: ['connections'],
          analytics: sampleAnalytics,
          analyticScope: null,
          analyticFetchEnabled: false,
          connectionsMapParams: defaultConnectionsParams,
          futureTurnOffset: 0,
          stellarCartography: defaultStellarCartography,
        }),
      { wrapper: createWrapper(client) }
    )

    await waitFor(() => {
      const queries = client.getQueryCache().getAll()
      expect(queries.some((q) => q.queryKey[3] === 'idle')).toBe(true)
    })
    expect(fetchAnalyticMap).not.toHaveBeenCalled()
  })

  it('combines map query results with memo deps from query state', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchAnalyticMap).mockClear()
    vi.mocked(combineMapData).mockClear()

    const { result } = renderHook(
      () =>
        useMapAnalyticQueries({
          viewMode: 'map',
          enabledAnalyticIds: ['connections'],
          analytics: sampleAnalytics,
          analyticScope: sampleScope,
          analyticFetchEnabled: true,
          connectionsMapParams: defaultConnectionsParams,
          futureTurnOffset: 0,
          stellarCartography: defaultStellarCartography,
        }),
      { wrapper: createWrapper(client) }
    )

    await waitFor(() => {
      expect(result.current.hasAnyData).toBe(true)
    })

    expect(combineMapData).toHaveBeenCalled()
    expect(result.current.mapIds).toEqual(['base-map', 'connections'])
    expect(result.current.combined.nodes.length).toBeGreaterThan(0)
  })
})
