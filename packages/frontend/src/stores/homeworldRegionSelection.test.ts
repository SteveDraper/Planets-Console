import { beforeEach, describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../api/mapRegionOverlayTypes'
import { HOMEWORLD_SECTOR_KIND } from '../analytics/homeworld-locator/homeworldSectorIndex'
import {
  defaultHomeworldRegionSelectionPreset,
  effectiveSelectedSectorIndexes,
} from '../analytics/homeworld-locator/homeworldRegionSelection'
import {
  HOMEWORLD_REGION_SELECTION_STORAGE_KEY,
  useHomeworldRegionSelectionStore,
} from './homeworldRegionSelection'

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

describe('homeworldRegionSelection store', () => {
  beforeEach(() => {
    localStorage.removeItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)
    localStorage.removeItem('planets-console-homeworld-region-display')
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: defaultHomeworldRegionSelectionPreset(),
      selectedSectorIndexes: null,
      showEnvelopeOverlays: true,
    })
  })

  it('defaults to selected preset, null indexes (all), envelopes on', () => {
    const state = useHomeworldRegionSelectionStore.getState()
    expect(state.regionSelectionPreset).toBe('selected')
    expect(state.selectedSectorIndexes).toBeNull()
    expect(state.showEnvelopeOverlays).toBe(true)
  })

  it('updates preset only without rewriting stored indexes', () => {
    const overlays = [sector('homeworld-sector-0', true), sector('homeworld-sector-1', false)]
    useHomeworldRegionSelectionStore.setState({ selectedSectorIndexes: [1] })
    useHomeworldRegionSelectionStore.getState().setRegionSelectionPreset('pinned')
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('pinned')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([1])
    expect(
      effectiveSelectedSectorIndexes(
        overlays,
        useHomeworldRegionSelectionStore.getState().regionSelectionPreset,
        useHomeworldRegionSelectionStore.getState().selectedSectorIndexes
      )
    ).toEqual([0])

    useHomeworldRegionSelectionStore.getState().setRegionSelectionPreset('unpinned')
    expect(
      effectiveSelectedSectorIndexes(
        overlays,
        useHomeworldRegionSelectionStore.getState().regionSelectionPreset,
        useHomeworldRegionSelectionStore.getState().selectedSectorIndexes
      )
    ).toEqual([1])
  })

  it('toggles from default-all against overlays, not empty', () => {
    const overlays = [
      sector('homeworld-sector-0', true),
      sector('homeworld-sector-2', false),
      sector('homeworld-sector-3', false),
    ]
    useHomeworldRegionSelectionStore.getState().toggleSectorIndex(2, overlays)
    const state = useHomeworldRegionSelectionStore.getState()
    expect(state.regionSelectionPreset).toBe('selected')
    expect(state.selectedSectorIndexes).toEqual([0, 3])
  })

  it('forces selected preset on manual sector toggle from pinned', () => {
    const overlays = [sector('homeworld-sector-0', true), sector('homeworld-sector-2', false)]
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'pinned',
      selectedSectorIndexes: null,
    })
    useHomeworldRegionSelectionStore.getState().toggleSectorIndex(0, overlays)
    const state = useHomeworldRegionSelectionStore.getState()
    expect(state.regionSelectionPreset).toBe('selected')
    // Effective pinned was [0]; toggle removes it.
    expect(state.selectedSectorIndexes).toEqual([])
  })

  it('preserves explicit empty selection under selected preset', () => {
    const overlays = [sector('homeworld-sector-0', true), sector('homeworld-sector-3', false)]
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [],
    })
    expect(
      effectiveSelectedSectorIndexes(
        overlays,
        'selected',
        useHomeworldRegionSelectionStore.getState().selectedSectorIndexes
      )
    ).toEqual([])
  })

  it('persists preference fields to localStorage', () => {
    const overlays = [sector('homeworld-sector-4', false)]
    useHomeworldRegionSelectionStore.getState().setShowEnvelopeOverlays(false)
    useHomeworldRegionSelectionStore.getState().toggleSectorIndex(4, overlays)
    const raw = localStorage.getItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('"showEnvelopeOverlays":false')
    expect(raw).toContain('"selected"')
    // Default-all was [4]; toggle removes 4 → explicit empty.
    expect(raw).toContain('"selectedSectorIndexes":[]')
  })

  it('ignores the old display-mode storage key', () => {
    localStorage.setItem(
      'planets-console-homeworld-region-display',
      JSON.stringify({ state: { regionDisplayMode: 'all' }, version: 1 })
    )
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('selected')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toBeNull()
    expect(localStorage.getItem('planets-console-homeworld-region-display')).toContain(
      'regionDisplayMode'
    )
  })

  it('persists explicit empty selection across reload', () => {
    useHomeworldRegionSelectionStore.setState({ selectedSectorIndexes: [] })
    const raw = localStorage.getItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)
    expect(raw).toContain('"selectedSectorIndexes":[]')
  })

  it('migrates v2 explicit indexes to null (default-all under Selected)', async () => {
    localStorage.setItem(
      HOMEWORLD_REGION_SELECTION_STORAGE_KEY,
      JSON.stringify({
        state: {
          regionSelectionPreset: 'selected',
          selectedSectorIndexes: [0, 1, 2, 5],
          showEnvelopeOverlays: true,
        },
        version: 2,
      })
    )
    // Re-import persist by resetting and triggering rehydrate via a fresh read path:
    // zustand persist migrates on create; simulate migrate helper via setState after
    // clearing and re-applying storage through the store's persist API.
    await useHomeworldRegionSelectionStore.persist.rehydrate()
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe(
      'selected'
    )
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toBeNull()
  })

  it('ignores invalid preset values', () => {
    useHomeworldRegionSelectionStore.getState().setRegionSelectionPreset('pinned')
    useHomeworldRegionSelectionStore
      .getState()
      .setRegionSelectionPreset('off' as 'selected')
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('pinned')
  })
})
