/**
 * Map paint pipeline for homeworld region overlays.
 * Multi-select visibility + envelope toggle; no persistent planet/sector focus chrome.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  isHomeworldPlanetEnvelopeOverlay,
  isHomeworldSectorOverlay,
  parseHomeworldSectorIndex,
} from './homeworldSectorIndex'
import { applyHomeworldRegionStyle } from './homeworldRegionStyle'

export type HomeworldRegionPaintInput = {
  /** Overlays after visibility-kind preferences (homeworld sectors pass through). */
  overlays: readonly MapRegionOverlay[]
  /**
   * Already-resolved multi-select indexes (hook/lib
   * ``effectiveSelectedSectorIndexes``). Paint does not re-derive from preset.
   */
  effectiveSelectedSectorIndexes: readonly number[]
  /**
   * Show overlays checkbox: 81/162 disks for selected sectors, or for
   * planet-envelope overlays when sector wedges are absent.
   */
  showEnvelopeOverlays: boolean
}

/**
 * Filter ``regionOverlays`` for map paint by selected sector indexes and
 * envelope toggle. Non-homeworld overlays pass through unchanged.
 * Selected homeworld sectors keep outlines; envelope disks remain only when
 * ``showEnvelopeOverlays`` is true. Unselected homeworld sectors are omitted.
 * Planet-envelope overlays paint only when ``showEnvelopeOverlays`` is true.
 */
export function applyHomeworldRegionSelection(
  overlays: readonly MapRegionOverlay[],
  selectedSectorIndexes: readonly number[],
  showEnvelopeOverlays: boolean
): MapRegionOverlay[] {
  const selected = new Set(selectedSectorIndexes)
  const result: MapRegionOverlay[] = []
  for (const overlay of overlays) {
    if (isHomeworldPlanetEnvelopeOverlay(overlay)) {
      if (showEnvelopeOverlays) result.push(overlay)
      continue
    }
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
 * Filter homeworld sectors for map paint, then attach stroke style.
 *
 * - Outlines: ``effectiveSelectedSectorIndexes`` (caller-resolved)
 * - Sector envelope disks: only when ``showEnvelopeOverlays`` and sector selected
 * - Planet envelopes: only when ``showEnvelopeOverlays`` (no sector selection)
 */
export function buildHomeworldRegionOverlaysForPaint(
  input: HomeworldRegionPaintInput
): MapRegionOverlay[] {
  const filtered = applyHomeworldRegionSelection(
    input.overlays,
    input.effectiveSelectedSectorIndexes,
    input.showEnvelopeOverlays
  )
  return applyHomeworldRegionStyle(filtered)
}
