import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../api/mapRegionOverlayTypes'
import { HOMEWORLD_SECTOR_KIND } from './homeworldSectorIndex'
import {
  allHomeworldSectorIndexes,
  defaultHomeworldRegionSelectionPreset,
  defaultShowEnvelopeOverlays,
  effectiveSelectedSectorIndexes,
  isHomeworldRegionSelectionPreset,
  isHomeworldRegionSelectionUiPreset,
  isHomeworldSectorPinned,
  materializeSectorIndexesForPreset,
  regionSelectionPresetForUi,
  sectorIndexesForPreset,
  toggleSectorIndexInSelection,
} from './homeworldRegionSelection'

function sector(
  id: string,
  isPinned: boolean,
  disks?: { x: number; y: number; radius: number }[]
): MapRegionOverlay {
  return {
    kind: HOMEWORLD_SECTOR_KIND,
    id,
    fillColor: '#f97316',
    fillOpacity: 0.2,
    isPinned,
    geometry: {
      type: 'boundary',
      vertices: [
        { x: 1, y: 0 },
        { x: 0, y: 1 },
        { x: 0, y: 0.5 },
        { x: 0.5, y: 0 },
      ],
      edges: [
        { type: 'arc', centerX: 0, centerY: 0, clockwise: false },
        { type: 'line' },
        { type: 'arc', centerX: 0, centerY: 0, clockwise: true },
        { type: 'line' },
      ],
      ...(disks != null ? { disks } : {}),
    },
  }
}

function visibilityOverlay(): MapRegionOverlay {
  return {
    kind: 'ship-scan',
    id: 'vis-1',
    fillColor: '#38bdf8',
    fillOpacity: 0.28,
    geometry: {
      type: 'coverage',
      disks: [{ x: 0, y: 0, radius: 100 }],
      patches: [],
    },
  }
}

describe('homeworldRegionSelection', () => {
  it('defaults to init-only all and envelopes on', () => {
    expect(defaultHomeworldRegionSelectionPreset()).toBe('all')
    expect(defaultShowEnvelopeOverlays()).toBe(true)
  })

  it('recognizes internal and UI preset strings', () => {
    expect(isHomeworldRegionSelectionPreset('all')).toBe(true)
    expect(isHomeworldRegionSelectionPreset('pinned')).toBe(true)
    expect(isHomeworldRegionSelectionPreset('unpinned')).toBe(true)
    expect(isHomeworldRegionSelectionPreset('selected')).toBe(true)
    expect(isHomeworldRegionSelectionPreset('off')).toBe(false)
    expect(isHomeworldRegionSelectionUiPreset('selected')).toBe(true)
    expect(isHomeworldRegionSelectionUiPreset('all')).toBe(false)
  })

  it('maps all to Selected for the UI control', () => {
    expect(regionSelectionPresetForUi('all')).toBe('selected')
    expect(regionSelectionPresetForUi('pinned')).toBe('pinned')
  })

  it('treats missing isPinned as unpinned', () => {
    const noFlag: MapRegionOverlay = { ...sector('homeworld-sector-1', false) }
    delete noFlag.isPinned
    expect(isHomeworldSectorPinned(noFlag)).toBe(false)
  })

  it('collects sector indexes and preset rewrites', () => {
    const pinned = sector('homeworld-sector-0', true)
    const unpinned = sector('homeworld-sector-2', false)
    const visibility = visibilityOverlay()
    const all = [pinned, unpinned, visibility]

    expect(allHomeworldSectorIndexes(all)).toEqual([0, 2])
    expect(sectorIndexesForPreset(all, 'pinned')).toEqual([0])
    expect(sectorIndexesForPreset(all, 'unpinned')).toEqual([2])
    expect(materializeSectorIndexesForPreset(all, 'all')).toEqual([0, 2])
    expect(materializeSectorIndexesForPreset(all, 'pinned')).toEqual([0])
    expect(materializeSectorIndexesForPreset(all, 'selected', [2])).toEqual([2])
  })

  it('resolves effective selection from preset and stored indexes', () => {
    const overlays = [
      sector('homeworld-sector-0', true),
      sector('homeworld-sector-2', false),
      visibilityOverlay(),
    ]
    expect(effectiveSelectedSectorIndexes(overlays, 'all', [])).toEqual([0, 2])
    expect(effectiveSelectedSectorIndexes(overlays, 'selected', [])).toEqual([])
    expect(effectiveSelectedSectorIndexes(overlays, 'selected', [2])).toEqual([2])
    expect(effectiveSelectedSectorIndexes(overlays, 'pinned', [])).toEqual([0])
    expect(effectiveSelectedSectorIndexes(overlays, 'pinned', [2])).toEqual([0])
    expect(effectiveSelectedSectorIndexes(overlays, 'unpinned', [0])).toEqual([2])
  })

  it('toggles sector indexes uniquely and sorted', () => {
    expect(toggleSectorIndexInSelection([1, 3], 2)).toEqual([1, 2, 3])
    expect(toggleSectorIndexInSelection([1, 2, 3], 2)).toEqual([1, 3])
  })
})
