/**
 * Homeworld region selection: sticky preset + selected sector indexes + envelope toggle.
 * Replaces the superseded four-way region display mode.
 *
 * Internal preset ``all`` is init-only (UI shows Selected). Overlays-ready materialize
 * writes ``selected`` + an explicit index list via ``useHomeworldRegionSelectionMaterialize``.
 *
 * Lives under ``lib/`` so the selection store does not import from analytics.
 */

import type { MapRegionOverlay } from '../api/mapRegionOverlayTypes'
import {
  isHomeworldSectorOverlay,
  parseHomeworldSectorIndex,
} from './homeworldSectorIndex'

/** Full persisted / internal preset set (includes init-only ``all``). */
export type HomeworldRegionSelectionPreset = 'all' | 'pinned' | 'unpinned' | 'selected'

/** Presets exposed on the Region selection control (never ``all``). */
export type HomeworldRegionSelectionUiPreset = 'pinned' | 'unpinned' | 'selected'

export const HOMEWORLD_REGION_SELECTION_UI_PRESETS: readonly HomeworldRegionSelectionUiPreset[] =
  ['pinned', 'unpinned', 'selected'] as const

export const HOMEWORLD_REGION_SELECTION_PRESET_LABELS: Record<
  HomeworldRegionSelectionUiPreset,
  string
> = {
  pinned: 'Pinned',
  unpinned: 'Unpinned',
  selected: 'Selected',
}

/** Fresh install / migrated default: init-only ``all`` until overlays materialize. */
export function defaultHomeworldRegionSelectionPreset(): HomeworldRegionSelectionPreset {
  return 'all'
}

export function defaultShowEnvelopeOverlays(): boolean {
  return true
}

export function isHomeworldRegionSelectionPreset(
  value: unknown
): value is HomeworldRegionSelectionPreset {
  return (
    value === 'all' ||
    value === 'pinned' ||
    value === 'unpinned' ||
    value === 'selected'
  )
}

export function isHomeworldRegionSelectionUiPreset(
  value: unknown
): value is HomeworldRegionSelectionUiPreset {
  return value === 'pinned' || value === 'unpinned' || value === 'selected'
}

/** Map internal preset to the Region selection control value (``all`` → Selected). */
export function regionSelectionPresetForUi(
  preset: HomeworldRegionSelectionPreset
): HomeworldRegionSelectionUiPreset {
  return preset === 'all' ? 'selected' : preset
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
 * ``pinned`` / ``unpinned`` only; ``selected`` / ``all`` use other helpers.
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
 * Materialize the outline multi-select set for a preset rewrite.
 * ``selected`` keeps ``currentIndexes`` (caller supplies the prior effective set).
 */
export function materializeSectorIndexesForPreset(
  overlays: readonly MapRegionOverlay[],
  preset: HomeworldRegionSelectionPreset,
  currentIndexes: readonly number[] = []
): number[] {
  if (preset === 'all') return allHomeworldSectorIndexes(overlays)
  if (preset === 'pinned' || preset === 'unpinned') {
    return sectorIndexesForPreset(overlays, preset)
  }
  return [...currentIndexes]
}

/**
 * Resolve the outline multi-select set for paint / panel chrome.
 *
 * - ``all``: every current homeworld sector (until materialize writes ``selected``).
 * - ``pinned`` / ``unpinned``: derive from overlay facts (no continuous store sync).
 * - ``selected``: stored concrete multi-select (including ``[]`` = none).
 */
export function effectiveSelectedSectorIndexes(
  overlays: readonly MapRegionOverlay[],
  preset: HomeworldRegionSelectionPreset,
  storedSelectedSectorIndexes: readonly number[]
): number[] {
  if (preset === 'all') {
    return allHomeworldSectorIndexes(overlays)
  }
  if (preset === 'pinned' || preset === 'unpinned') {
    return sectorIndexesForPreset(overlays, preset)
  }
  return [...storedSelectedSectorIndexes]
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
 * Whether MapGraph may run init-only ``all`` → selected materialize.
 *
 * Requires the homeworld map layer to have **succeeded** -- not merely ``!pending``.
 * Failure-empty (errored layer omitted from combined) must not consume ``all``.
 * Success-empty (zero sectors / non-circular) may still materialize to ``selected`` + ``[]``.
 * ``mapLayersPending`` continues to block the base-map-only loading race.
 */
export function homeworldOverlaysReadyForMaterialize(input: {
  homeworldEnabled: boolean
  mapLayersPending: boolean
  homeworldMapLayerSucceeded: boolean
}): boolean {
  return (
    input.homeworldEnabled &&
    !input.mapLayersPending &&
    input.homeworldMapLayerSucceeded
  )
}
