import { beforeEach, describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../api/mapRegionOverlayTypes'
import { HOMEWORLD_SECTOR_KIND } from '../analytics/homeworld-locator/homeworldSectorIndex'
import { defaultHomeworldRegionSelectionPreset } from '../analytics/homeworld-locator/homeworldRegionSelection'
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
      selectedSectorIndexes: [],
      showEnvelopeOverlays: true,
    })
  })

  it('defaults to selected preset, empty indexes, envelopes on', () => {
    const state = useHomeworldRegionSelectionStore.getState()
    expect(state.regionSelectionPreset).toBe('selected')
    expect(state.selectedSectorIndexes).toEqual([])
    expect(state.showEnvelopeOverlays).toBe(true)
  })

  it('rewrites selected indexes when applying pinned/unpinned with overlays', () => {
    const overlays = [sector('homeworld-sector-0', true), sector('homeworld-sector-1', false)]
    useHomeworldRegionSelectionStore.getState().setRegionSelectionPreset('pinned', overlays)
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('pinned')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([0])

    useHomeworldRegionSelectionStore.getState().setRegionSelectionPreset('unpinned', overlays)
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([1])
  })

  it('forces selected preset on manual sector toggle', () => {
    useHomeworldRegionSelectionStore.setState({ regionSelectionPreset: 'pinned' })
    useHomeworldRegionSelectionStore.getState().toggleSectorIndex(2)
    const state = useHomeworldRegionSelectionStore.getState()
    expect(state.regionSelectionPreset).toBe('selected')
    expect(state.selectedSectorIndexes).toEqual([2])
  })

  it('seeds empty selection to all sector indexes on sync', () => {
    const overlays = [sector('homeworld-sector-0', true), sector('homeworld-sector-3', false)]
    useHomeworldRegionSelectionStore.getState().syncSelectionWithOverlays(overlays)
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([0, 3])
  })

  it('re-applies pinned rewrite on sync when preset is pinned', () => {
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'pinned',
      selectedSectorIndexes: [9],
    })
    const overlays = [sector('homeworld-sector-0', true), sector('homeworld-sector-1', false)]
    useHomeworldRegionSelectionStore.getState().syncSelectionWithOverlays(overlays)
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([0])
  })

  it('persists preference fields to localStorage', () => {
    useHomeworldRegionSelectionStore.getState().setShowEnvelopeOverlays(false)
    useHomeworldRegionSelectionStore.getState().toggleSectorIndex(4)
    const raw = localStorage.getItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('"showEnvelopeOverlays":false')
    expect(raw).toContain('"selected"')
    expect(raw).toContain('4')
  })

  it('ignores the old display-mode storage key', () => {
    localStorage.setItem(
      'planets-console-homeworld-region-display',
      JSON.stringify({ state: { regionDisplayMode: 'all' }, version: 1 })
    )
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('selected')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
    expect(localStorage.getItem('planets-console-homeworld-region-display')).toContain(
      'regionDisplayMode'
    )
  })

  it('ignores invalid preset values', () => {
    useHomeworldRegionSelectionStore.getState().setRegionSelectionPreset('pinned')
    useHomeworldRegionSelectionStore
      .getState()
      .setRegionSelectionPreset('off' as 'selected')
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('pinned')
  })
})
