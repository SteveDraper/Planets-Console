import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  HOMEWORLD_SECTOR_KIND,
  applyHomeworldRegionDisplayMode,
  defaultHomeworldRegionDisplayMode,
  isHomeworldRegionDisplayMode,
  isHomeworldSectorOverlay,
} from './homeworldRegionDisplayMode'

function sector(id: string, isPinned: boolean): MapRegionOverlay {
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

describe('homeworldRegionDisplayMode', () => {
  it('defaults to un-pinned', () => {
    expect(defaultHomeworldRegionDisplayMode()).toBe('un-pinned')
  })

  it('recognizes valid mode strings', () => {
    expect(isHomeworldRegionDisplayMode('off')).toBe(true)
    expect(isHomeworldRegionDisplayMode('un-pinned')).toBe(true)
    expect(isHomeworldRegionDisplayMode('pinned')).toBe(true)
    expect(isHomeworldRegionDisplayMode('all')).toBe(true)
    expect(isHomeworldRegionDisplayMode('always')).toBe(false)
    expect(isHomeworldRegionDisplayMode(null)).toBe(false)
  })

  it('identifies homeworld sector overlays', () => {
    expect(isHomeworldSectorOverlay(sector('a', false))).toBe(true)
    expect(isHomeworldSectorOverlay(visibilityOverlay())).toBe(false)
  })

  it('filters by mode matrix and passes non-homeworld through', () => {
    const pinned = sector('pinned', true)
    const unpinned = sector('unpinned', false)
    const visibility = visibilityOverlay()
    const all = [pinned, unpinned, visibility]

    expect(applyHomeworldRegionDisplayMode(all, 'off').map((o) => o.id)).toEqual([
      'vis-1',
    ])
    expect(applyHomeworldRegionDisplayMode(all, 'un-pinned').map((o) => o.id)).toEqual([
      'unpinned',
      'vis-1',
    ])
    expect(applyHomeworldRegionDisplayMode(all, 'pinned').map((o) => o.id)).toEqual([
      'pinned',
      'vis-1',
    ])
    expect(applyHomeworldRegionDisplayMode(all, 'all').map((o) => o.id)).toEqual([
      'pinned',
      'unpinned',
      'vis-1',
    ])
  })

  it('treats missing isPinned as un-pinned', () => {
    const noFlag: MapRegionOverlay = {
      ...sector('implicit', false),
    }
    delete noFlag.isPinned
    expect(applyHomeworldRegionDisplayMode([noFlag], 'un-pinned')).toHaveLength(1)
    expect(applyHomeworldRegionDisplayMode([noFlag], 'pinned')).toHaveLength(0)
  })
})
