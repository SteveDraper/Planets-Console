/**
 * Homeworld region selection: sticky preset + selected sector indexes + envelope toggle.
 * Replaces the superseded four-way region display mode.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  HOMEWORLD_SECTOR_KIND,
  isHomeworldSectorOverlay,
  parseHomeworldSectorIndex,
} from './homeworldSectorIndex'

export type HomeworldRegionSelectionPreset = 'pinned' | 'unpinned' | 'selected'

export const HOMEWORLD_REGION_SELECTION_PRESETS: readonly HomeworldRegionSelectionPreset[] = [
  'pinned',
  'unpinned',
  'selected',
] as const

export const HOMEWORLD_REGION_SELECTION_PRESET_LABELS: Record<
  HomeworldRegionSelectionPreset,
  string
> = {
  pinned: 'Pinned',
  unpinned: 'Unpinned',
  selected: 'Selected',
}

export function defaultHomeworldRegionSelectionPreset(): HomeworldRegionSelectionPreset {
  return 'selected'
}

export function defaultShowEnvelopeOverlays(): boolean {
  return true
}

export function isHomeworldRegionSelectionPreset(
  value: unknown
): value is HomeworldRegionSelectionPreset {
  return value === 'pinned' || value === 'unpinned' || value === 'selected'
}

/** True when the sector is pinned (determined HW + known owner). Missing flag = unpinned. */
export function isHomeworldSectorPinned(overlay: MapRegionOverlay): boolean {
  return overlay.isPinned === true
}

/** Sector indexes for every homeworld-sector overlay (stable parse order). */
export function allHomeworldSectorIndexes(
  overlays: readonly MapRegionOverlay[]
): number[] {
  const indexes: number[] = []
  for (const overlay of overlays) {
    if (!isHomeworldSectorOverlay(overlay)) continue
    const index = parseHomeworldSectorIndex(overlay.id)
    if (index != null) indexes.push(index)
  }
  return indexes
}

/**
 * Sector indexes matching a rewrite preset.
 * ``pinned`` / ``unpinned`` only; ``selected`` does not rewrite from overlays.
 */
export function sectorIndexesForPreset(
  overlays: readonly MapRegionOverlay[],
  preset: 'pinned' | 'unpinned'
): number[] {
  const wantPinned = preset === 'pinned'
  const indexes: number[] = []
  for (const overlay of overlays) {
    if (!isHomeworldSectorOverlay(overlay)) continue
    if (isHomeworldSectorPinned(overlay) !== wantPinned) continue
    const index = parseHomeworldSectorIndex(overlay.id)
    if (index != null) indexes.push(index)
  }
  return indexes
}

/**
 * Resolve the outline multi-select set for paint / panel chrome.
 *
 * - ``pinned`` / ``unpinned``: derive from overlay facts (controller does not store indexes).
 * - ``selected`` + ``null`` stored: all current homeworld sector indexes (session default).
 * - ``selected`` + array: explicit multi-select (including ``[]`` = none).
 */
export function effectiveSelectedSectorIndexes(
  overlays: readonly MapRegionOverlay[],
  preset: HomeworldRegionSelectionPreset,
  storedSelectedSectorIndexes: readonly number[] | null
): number[] {
  if (preset === 'pinned' || preset === 'unpinned') {
    return sectorIndexesForPreset(overlays, preset)
  }
  return storedSelectedSectorIndexes != null
    ? [...storedSelectedSectorIndexes]
    : allHomeworldSectorIndexes(overlays)
}

/**
 * Toggle one sector index in a selected set; returns a new sorted unique array.
 */
export function toggleSectorIndexInSelection(
  selectedSectorIndexes: readonly number[],
  sectorIndex: number
): number[] {
  const set = new Set(selectedSectorIndexes)
  if (set.has(sectorIndex)) {
    set.delete(sectorIndex)
  } else {
    set.add(sectorIndex)
  }
  return [...set].sort((a, b) => a - b)
}

/**
 * Filter ``regionOverlays`` for map paint by selected sector indexes and
 * envelope toggle (``filterHomeworldSectorsForPaint`` semantics).
 * Non-homeworld overlays pass through unchanged.
 * Selected homeworld sectors keep outlines; envelope disks remain only when
 * ``showEnvelopeOverlays`` is true. Unselected homeworld sectors are omitted.
 */
export function applyHomeworldRegionSelection(
  overlays: readonly MapRegionOverlay[],
  selectedSectorIndexes: readonly number[],
  showEnvelopeOverlays: boolean
): MapRegionOverlay[] {
  const selected = new Set(selectedSectorIndexes)
  const result: MapRegionOverlay[] = []
  for (const overlay of overlays) {
    if (!isHomeworldSectorOverlay(overlay)) {
      result.push(overlay)
      continue
    }
    const index = parseHomeworldSectorIndex(overlay.id)
    if (index == null || !selected.has(index)) continue
    if (showEnvelopeOverlays || overlay.geometry.type !== 'boundary') {
      result.push(overlay)
      continue
    }
    result.push({
      ...overlay,
      geometry: {
        type: 'boundary',
        vertices: overlay.geometry.vertices,
        edges: overlay.geometry.edges,
      },
    })
  }
  return result
}

export { HOMEWORLD_SECTOR_KIND, isHomeworldSectorOverlay }
