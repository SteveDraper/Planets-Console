import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { fetchFleetComponentCatalog } from '../../api/bff'
import {
  EMPTY_FLEET_COMPONENT_CATALOG,
  type FleetComponentCatalog,
} from './fleetComponentCatalog'
import { useFleetComponentCatalogQuery } from './useFleetComponentCatalogQuery'

vi.mock('../../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bff')>()
  return {
    ...actual,
    fetchFleetComponentCatalog: vi.fn(),
  }
})

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

const catalog: FleetComponentCatalog = {
  hulls: { '13': 'Cruiser A' },
  engines: { '9': 'Transwarp' },
  beams: {},
  torpedoes: {},
}

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useFleetComponentCatalogQuery', () => {
  beforeEach(() => {
    vi.mocked(fetchFleetComponentCatalog).mockReset()
  })

  it('returns catalog from fetch on the happy path', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchFleetComponentCatalog).mockResolvedValue(catalog)

    const { result } = renderHook(() => useFleetComponentCatalogQuery(scope, true), {
      wrapper: createWrapper(client),
    })

    expect(result.current).toEqual(EMPTY_FLEET_COMPONENT_CATALOG)

    await waitFor(() => {
      expect(result.current).toEqual(catalog)
    })
    expect(fetchFleetComponentCatalog).toHaveBeenCalledWith(scope)
  })

  it('stays non-blocking on fetch error and returns empty catalog', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(fetchFleetComponentCatalog).mockRejectedValue(new Error('catalog unavailable'))

    const { result } = renderHook(() => useFleetComponentCatalogQuery(scope, true), {
      wrapper: createWrapper(client),
    })

    expect(result.current).toEqual(EMPTY_FLEET_COMPONENT_CATALOG)

    await waitFor(() => {
      expect(fetchFleetComponentCatalog).toHaveBeenCalledWith(scope)
    })

    expect(result.current).toEqual(EMPTY_FLEET_COMPONENT_CATALOG)
  })
})
