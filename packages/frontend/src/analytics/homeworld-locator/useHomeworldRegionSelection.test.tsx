import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  HOMEWORLD_REGION_SELECTION_STORAGE_KEY,
  useHomeworldRegionSelectionStore,
} from '../../stores/homeworldRegionSelectionStore'
import { HOMEWORLD_SECTOR_KIND } from './homeworldSectorIndex'
import {
  useEffectiveHomeworldSectorIndexes,
  useHomeworldRegionSelection,
  useHomeworldRegionSelectionMaterialize,
} from './useHomeworldRegionSelection'

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

/**
 * Production split: MapGraph materializes from combined-map overlays; Tile mounts
 * ``useHomeworldRegionSelection`` for panel/controls with overlays from the shared
 * homeworld map observer (``useHomeworldLocatorMapOverlays``).
 */
function useTileSelectionWithMapMaterialize(
  overlays: readonly MapRegionOverlay[],
  overlaysReady: boolean
) {
  const selection = useHomeworldRegionSelection({
    overlays,
    overlaysReady,
  })
  useHomeworldRegionSelectionMaterialize(overlays, overlaysReady)
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

  it('materializes all to selected + [] when overlays are ready but empty (success-empty)', async () => {
    renderHook(() => useHomeworldRegionSelectionMaterialize([], true))

    await waitFor(() => {
      expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe(
        'selected'
      )
      expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
    })
  })

  it('does not materialize when overlaysReady is false', () => {
    renderHook(() =>
      useHomeworldRegionSelectionMaterialize(SECTOR_OVERLAYS, false)
    )
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('all')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
  })

  it('does not materialize failure-empty overlays while still on init-only all', () => {
    // overlaysReady false stands for failed/pending homeworld layer; empty overlays
    // alone must not be treated as success-empty.
    renderHook(() => useHomeworldRegionSelectionMaterialize([], false))
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('all')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
  })

  it('does not clobber a sector toggle that landed before the materialize effect ran', () => {
    const { result, rerender } = renderHook(
      ({ ready }) => useTileSelectionWithMapMaterialize(SECTOR_OVERLAYS, ready),
      { initialProps: { ready: false } }
    )

    // Same act: overlays become ready (schedules materialize with closed-over ``all``),
    // then the user toggles a sector (writes ``selected`` + subset). Effect must read
    // getState() so it does not rewrite the full index list.
    act(() => {
      rerender({ ready: true })
      result.current.toggleSectorIndex(1)
    })

    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe(
      'selected'
    )
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([0])
  })

  it('does not rewrite stored indexes while preset is pinned', () => {
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'pinned',
      selectedSectorIndexes: [0, 1],
      showEnvelopeOverlays: true,
    })

    renderHook(() => useHomeworldRegionSelectionMaterialize(SECTOR_OVERLAYS, true))

    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe(
      'pinned'
    )
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([
      0, 1,
    ])
  })
})

describe('useEffectiveHomeworldSectorIndexes', () => {
  beforeEach(() => {
    localStorage.removeItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'all',
      selectedSectorIndexes: [],
      showEnvelopeOverlays: true,
    })
  })

  it('derives all homeworld indexes while preset is init-only all', () => {
    const { result } = renderHook(() =>
      useEffectiveHomeworldSectorIndexes(SECTOR_OVERLAYS)
    )
    expect(result.current.selectedSectorIndexes).toEqual([0, 1])
    expect([...result.current.selectedSectorIndexSet]).toEqual([0, 1])
  })

  it('derives pinned/unpinned from overlays and ignores stored indexes', () => {
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'pinned',
      selectedSectorIndexes: [1],
      showEnvelopeOverlays: true,
    })
    const { result, rerender } = renderHook(
      ({ overlays }) => useEffectiveHomeworldSectorIndexes(overlays),
      { initialProps: { overlays: SECTOR_OVERLAYS } }
    )
    expect(result.current.selectedSectorIndexes).toEqual([0])

    act(() => {
      useHomeworldRegionSelectionStore.setState({
        regionSelectionPreset: 'unpinned',
        selectedSectorIndexes: [0],
      })
    })
    rerender({ overlays: SECTOR_OVERLAYS })
    expect(result.current.selectedSectorIndexes).toEqual([1])
  })

  it('returns stored indexes for selected preset', () => {
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [1],
      showEnvelopeOverlays: true,
    })
    const { result } = renderHook(() =>
      useEffectiveHomeworldSectorIndexes(SECTOR_OVERLAYS)
    )
    expect(result.current.selectedSectorIndexes).toEqual([1])
    expect(result.current.selectedSectorIndexSet.has(1)).toBe(true)
    expect(result.current.selectedSectorIndexSet.has(0)).toBe(false)
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
  })

  it('does not materialize when only the read hook is mounted', () => {
    const { result } = renderHook(() =>
      useHomeworldRegionSelection({
        overlays: SECTOR_OVERLAYS,
        overlaysReady: true,
      })
    )

    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('all')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
    // Effective selection still reflects ``all`` overlays without a store write.
    expect(result.current.selectedSectorIndexes).toEqual([0, 1])
    expect(result.current.uiPreset).toBe('selected')
  })

  it('stores empty indexes for pinned/unpinned; Selected snapshots the effective set', async () => {
    const { result } = renderHook(() =>
      useTileSelectionWithMapMaterialize(SECTOR_OVERLAYS, true)
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
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
    expect(result.current.uiPreset).toBe('pinned')
    // Effective set still derives from overlays (ignore empty store).
    expect(result.current.selectedSectorIndexes).toEqual([0])

    act(() => {
      result.current.setUiPreset('selected')
    })
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe(
      'selected'
    )
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([0])

    act(() => {
      result.current.setUiPreset('unpinned')
    })
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe(
      'unpinned'
    )
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
    expect(result.current.selectedSectorIndexes).toEqual([1])

    act(() => {
      result.current.setUiPreset('selected')
    })
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([1])
  })

  it('forces selected and toggles against the effective set', async () => {
    const { result } = renderHook(() =>
      useTileSelectionWithMapMaterialize(SECTOR_OVERLAYS, true)
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
