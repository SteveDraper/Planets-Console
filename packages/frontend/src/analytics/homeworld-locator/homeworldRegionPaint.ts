/**
 * Map paint pipeline for homeworld region overlays.
 * Multi-select visibility + envelope toggle are separate from assert-focus highlight.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import type { HomeworldLocatorSelection } from '../../stores/homeworldLocatorSelection'
import {
  applyHomeworldRegionSelection,
  effectiveSelectedSectorIndexes,
  type HomeworldRegionSelectionPreset,
} from './homeworldRegionSelection'
import { applyHomeworldRegionStyle } from './homeworldRegionStyle'
import {
  resolveHomeworldSelectedSectorIndex,
  type HomeworldSelectedSectorMarker,
} from './resolveHomeworldSelectedSectorIndex'

export type HomeworldRegionPaintInput = {
  /** Overlays after visibility-kind preferences (homeworld sectors pass through). */
  overlays: readonly MapRegionOverlay[]
  /** Region selection preset from the homeworld region selection store. */
  regionSelectionPreset: HomeworldRegionSelectionPreset
  /**
   * Stored multi-select indexes. Under ``all`` / pinned / unpinned, paint still
   * resolves via ``effectiveSelectedSectorIndexes`` until the selection hook
   * materializes a concrete ``selected`` list.
   */
  selectedSectorIndexes: readonly number[]
  /** Show overlays checkbox: 81/162 disks for selected sectors only. */
  showEnvelopeOverlays: boolean
  /**
   * Assert-focus selection (panel/map highlight). Distinct from
   * region-selection outline multi-select.
   */
  assertFocusSelection: HomeworldLocatorSelection
  homeworldMarkers: readonly HomeworldSelectedSectorMarker[]
}

/**
 * Filter homeworld sectors for map paint, then attach stroke style including
 * assert-focus highlight when the focused sector remains visible.
 *
 * - Outlines: effective selected set (preset + stored / all)
 * - Envelope disks: only when ``showEnvelopeOverlays`` and sector selected
 * - Assert-focus cyan/amber stroke: from ``assertFocusSelection``, not multi-select
 */
export function buildHomeworldRegionOverlaysForPaint(
  input: HomeworldRegionPaintInput
): MapRegionOverlay[] {
  const selectedIndexes = effectiveSelectedSectorIndexes(
    input.overlays,
    input.regionSelectionPreset,
    input.selectedSectorIndexes
  )
  const filtered = applyHomeworldRegionSelection(
    input.overlays,
    selectedIndexes,
    input.showEnvelopeOverlays
  )
  const assertFocusSectorIndex = resolveHomeworldSelectedSectorIndex(
    input.assertFocusSelection,
    input.homeworldMarkers,
    filtered
  )
  return applyHomeworldRegionStyle(filtered, {
    selectedSectorIndex: assertFocusSectorIndex,
  })
}
