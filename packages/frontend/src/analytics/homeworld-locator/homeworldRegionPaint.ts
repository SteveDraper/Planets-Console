/**
 * Map paint pipeline for homeworld region overlays.
 * Multi-select visibility + envelope toggle are separate from assert-focus highlight.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import type { HomeworldLocatorSelection } from '../../stores/homeworldLocatorSelection'
import { applyHomeworldRegionSelection } from './homeworldRegionSelection'
import { applyHomeworldRegionStyle } from './homeworldRegionStyle'
import {
  resolveHomeworldSelectedSectorIndex,
  type HomeworldSelectedSectorMarker,
} from './resolveHomeworldSelectedSectorIndex'

export type HomeworldRegionPaintInput = {
  /** Overlays after visibility-kind preferences (homeworld sectors pass through). */
  overlays: readonly MapRegionOverlay[]
  /** Multi-select outline set from homeworld region selection store. ``null`` = not yet seeded. */
  selectedSectorIndexes: readonly number[] | null
  /** Show overlays checkbox: 81/162 disks for selected sectors only. */
  showEnvelopeOverlays: boolean
  /**
   * Assert-focus selection (panel/table/map highlight). Distinct from
   * ``selectedSectorIndexes`` outline multi-select.
   */
  assertFocusSelection: HomeworldLocatorSelection
  homeworldMarkers: readonly HomeworldSelectedSectorMarker[]
}

/**
 * Filter homeworld sectors for map paint, then attach stroke style including
 * assert-focus highlight when the focused sector remains visible.
 *
 * - Outlines: only sectors in ``selectedSectorIndexes``
 * - Envelope disks: only when ``showEnvelopeOverlays`` and sector selected
 * - Assert-focus cyan/amber stroke: from ``assertFocusSelection``, not multi-select
 */
export function buildHomeworldRegionOverlaysForPaint(
  input: HomeworldRegionPaintInput
): MapRegionOverlay[] {
  const filtered = applyHomeworldRegionSelection(
    input.overlays,
    input.selectedSectorIndexes ?? [],
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
