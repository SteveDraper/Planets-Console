import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  HOMEWORLD_REGION_SELECTION_STORAGE_KEY,
  useHomeworldRegionSelectionStore,
} from '../../stores/homeworldRegionSelectionStore'
import { HOMEWORLD_SECTOR_KIND } from './homeworldSectorIndex'
import { fetchHomeworldLocatorMap } from './api'
import {
  useHomeworldRegionSelection,
  useHomeworldRegionSelectionMaterialize,
} from './useHomeworldRegionSelection'

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

const SECTOR_OVERLAYS: readonly MapRegionOverlay[] = [
  sector('homeworld-sector-0', true),
  sector('homeworld-sector-1', false),
]

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

/**
 * Production split: MapGraph materializes from combined-map overlays; Tile mounts
 * ``useHomeworldRegionSelection`` for panel/controls. Overlays here stand in for
 * homeworld sectors already present on ``data.regionOverlays``.
 */
function useTileSelectionWithMapMaterialize(fetchEnabled: boolean) {
  const selection = useHomeworldRegionSelection({
    analyticScope: scope,
    fetchEnabled,
  })
  useHomeworldRegionSelectionMaterialize(
    selection.overlays,
    fetchEnabled && selection.overlaysReady
  )
  return selection
}

describe('useHomeworldRegionSelectionMaterialize', () => {
  beforeEach(() => {
    localStorage.removeItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'all',
      selectedSectorIndexes: [],
      showEnvelopeOverlays: true,
    })
  })

  it('materializes all to selected + full indexes when overlays are ready', async () => {
    renderHook(() =>
      useHomeworldRegionSelectionMaterialize(SECTOR_OVERLAYS, true)
    )

    await waitFor(() => {
      expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe(
        'selected'
      )
      expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([
        0, 1,
      ])
    })
  })

  it('does not materialize when overlaysReady is false', () => {
    renderHook(() =>
      useHomeworldRegionSelectionMaterialize(SECTOR_OVERLAYS, false)
    )
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('all')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
  })

  it('keeps pinned stored indexes aligned with overlay facts', async () => {
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'pinned',
      selectedSectorIndexes: [0, 1],
      showEnvelopeOverlays: true,
    })

    const { rerender } = renderHook(
      ({ overlays }: { overlays: readonly MapRegionOverlay[] }) =>
        useHomeworldRegionSelectionMaterialize(overlays, true),
      { initialProps: { overlays: SECTOR_OVERLAYS } }
    )

    await waitFor(() => {
      expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([
        0,
      ])
    })

    rerender({
      overlays: [
        sector('homeworld-sector-0', false),
        sector('homeworld-sector-1', true),
      ],
    })

    await waitFor(() => {
      expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([
        1,
      ])
    })
  })
})

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
      regionOverlays: [...SECTOR_OVERLAYS],
      markers: [],
    })
  })

  it('does not materialize when only the read hook is mounted', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(
      () => useHomeworldRegionSelection({ analyticScope: scope, fetchEnabled: true }),
      { wrapper: createWrapper(client) }
    )

    await waitFor(() => {
      expect(result.current.overlaysReady).toBe(true)
    })
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('all')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
    // Effective selection still reflects ``all`` overlays without a store write.
    expect(result.current.selectedSectorIndexes).toEqual([0, 1])
    expect(result.current.uiPreset).toBe('selected')
  })

  it('materializes pinned on UI preset change and rematerializes on overlay facts', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(() => useTileSelectionWithMapMaterialize(true), {
      wrapper: createWrapper(client),
    })

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
    const { result } = renderHook(() => useTileSelectionWithMapMaterialize(true), {
      wrapper: createWrapper(client),
    })

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
