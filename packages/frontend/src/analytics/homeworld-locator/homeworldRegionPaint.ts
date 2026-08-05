/**
 * Map paint pipeline for homeworld region overlays.
 * Multi-select visibility + envelope toggle are separate from assert-focus highlight.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import type { HomeworldLocatorSelection } from '../../stores/homeworldLocatorSelection'
import {
  effectiveSelectedSectorIndexes,
  type HomeworldRegionSelectionPreset,
} from '../../lib/homeworldRegionSelection'
import {
  isHomeworldSectorOverlay,
  parseHomeworldSectorIndex,
} from './homeworldSectorIndex'
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
 * Filter ``regionOverlays`` for map paint by selected sector indexes and
 * envelope toggle. Non-homeworld overlays pass through unchanged.
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
