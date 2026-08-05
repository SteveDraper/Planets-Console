import { beforeEach, describe, expect, it } from 'vitest'
import { defaultHomeworldRegionSelectionPreset } from '../analytics/homeworld-locator/homeworldRegionSelection'
import {
  HOMEWORLD_REGION_SELECTION_STORAGE_KEY,
  useHomeworldRegionSelectionStore,
} from './homeworldRegionSelection'

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

  it('defaults to all preset, empty indexes, envelopes on', () => {
    const state = useHomeworldRegionSelectionStore.getState()
    expect(state.regionSelectionPreset).toBe('all')
    expect(state.selectedSectorIndexes).toEqual([])
    expect(state.showEnvelopeOverlays).toBe(true)
  })

  it('replaces preset and indexes together', () => {
    useHomeworldRegionSelectionStore
      .getState()
      .setRegionSelectionState('pinned', [0])
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('pinned')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([0])

    useHomeworldRegionSelectionStore
      .getState()
      .setRegionSelectionState('selected', [0, 2])
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([0, 2])
  })

  it('sorts indexes on write', () => {
    useHomeworldRegionSelectionStore
      .getState()
      .setRegionSelectionState('selected', [3, 1, 2])
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([1, 2, 3])
  })

  it('persists preference fields to localStorage', () => {
    useHomeworldRegionSelectionStore.getState().setShowEnvelopeOverlays(false)
    useHomeworldRegionSelectionStore
      .getState()
      .setRegionSelectionState('selected', [])
    const raw = localStorage.getItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('"showEnvelopeOverlays":false')
    expect(raw).toContain('"selected"')
    expect(raw).toContain('"selectedSectorIndexes":[]')
  })

  it('ignores the old display-mode storage key', () => {
    localStorage.setItem(
      'planets-console-homeworld-region-display',
      JSON.stringify({ state: { regionDisplayMode: 'all' }, version: 1 })
    )
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('all')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
    expect(localStorage.getItem('planets-console-homeworld-region-display')).toContain(
      'regionDisplayMode'
    )
  })

  it('persists explicit empty selection across reload', () => {
    useHomeworldRegionSelectionStore.setState({
      regionSelectionPreset: 'selected',
      selectedSectorIndexes: [],
    })
    const raw = localStorage.getItem(HOMEWORLD_REGION_SELECTION_STORAGE_KEY)
    expect(raw).toContain('"selectedSectorIndexes":[]')
    expect(raw).toContain('"selected"')
  })

  it('migrates v3 selected+null to all + empty indexes', async () => {
    localStorage.setItem(
      HOMEWORLD_REGION_SELECTION_STORAGE_KEY,
      JSON.stringify({
        state: {
          regionSelectionPreset: 'selected',
          selectedSectorIndexes: null,
          showEnvelopeOverlays: true,
        },
        version: 3,
      })
    )
    await useHomeworldRegionSelectionStore.persist.rehydrate()
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('all')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([])
  })

  it('migrates v2 selected+concrete indexes without wiping', async () => {
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
    await useHomeworldRegionSelectionStore.persist.rehydrate()
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe(
      'selected'
    )
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([
      0, 1, 2, 5,
    ])
  })

  it('ignores invalid preset values on setRegionSelectionState', () => {
    useHomeworldRegionSelectionStore.getState().setRegionSelectionState('pinned', [0])
    useHomeworldRegionSelectionStore
      .getState()
      .setRegionSelectionState('off' as 'selected', [1])
    expect(useHomeworldRegionSelectionStore.getState().regionSelectionPreset).toBe('pinned')
    expect(useHomeworldRegionSelectionStore.getState().selectedSectorIndexes).toEqual([0])
  })
})
