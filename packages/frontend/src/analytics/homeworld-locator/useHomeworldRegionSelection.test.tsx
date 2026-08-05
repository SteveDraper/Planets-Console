import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  HOMEWORLD_REGION_SELECTION_STORAGE_KEY,
  useHomeworldRegionSelectionStore,
} from '../../stores/homeworldRegionSelection'
import { HOMEWORLD_SECTOR_KIND } from './homeworldSectorIndex'
import { fetchHomeworldLocatorMap } from './api'
import { useHomeworldRegionSelection } from './useHomeworldRegionSelection'

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

function sector(id: string, isPinned: boolean): MapRegionOverlay {
  return {
    kind: HOMEWORLD_SECTOR_KIND,
    id,
    fillColor: '#f97316',
    fillOpacity: 0,
    isPinned,
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
}

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useHomeworldRegionSelection', () => {
  beforeEach(() => {
    localStorage.removeItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'all',
      selectedSectorIndexes: [],
      showEnvelopeOverlays: true,
    })
    vi.mocked(fetchHomeworldLocatorMap).mockResolvedValue({
      analyticId: 'homeworld-locator',
      available: true,
      baselineDegraded: false,
      regionOverlays: [
        sector('homeworld-sector-0', true),
        sector('homeworld-sector-1', false),
      ],
      markers: [],
    })
  })

  it('materializes all to selected + full indexes when overlays are ready', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(
      () => useHomeworldRegionSelection({ analyticScope: scope, fetchEnabled: true }),
      { wrapper: createWrapper(client) }
    )

    expect(result.current.uiPreset).toBe('selected')

    await waitFor(() => {
      expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe(
        'selected'
      )
      expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([
        0, 1,
      ])
    })
    expect(result.current.uiPreset).toBe('selected')
    expect(result.current.selectedSectorIndexes).toEqual([0, 1])
  })

  it('materializes pinned on UI preset change and rematerializes on overlay facts', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(
      () => useHomeworldRegionSelection({ analyticScope: scope, fetchEnabled: true }),
      { wrapper: createWrapper(client) }
    )

    await waitFor(() => {
      expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe(
        'selected'
      )
    })

    act(() => {
      result.current.setUiPreset('pinned')
    })
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('pinned')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([0])
    expect(result.current.uiPreset).toBe('pinned')

    act(() => {
      result.current.setUiPreset('selected')
    })
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([0])
  })

  it('forces selected and toggles against the effective set', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(
      () => useHomeworldRegionSelection({ analyticScope: scope, fetchEnabled: true }),
      { wrapper: createWrapper(client) }
    )

    await waitFor(() => {
      expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([
        0, 1,
      ])
    })

    act(() => {
      result.current.setUiPreset('pinned')
    })
    act(() => {
      result.current.toggleSectorIndex(0)
    })
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe(
      'selected'
    )
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
  })
})
