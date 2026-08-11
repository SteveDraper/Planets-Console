import type { MapRegionOverlay, MapRegionOverlayPaint } from '../../api/mapRegionOverlayTypes'
import {
  isHomeworldPlanetEnvelopeOverlay,
  isHomeworldSectorOverlay,
} from './homeworldSectorIndex'
import { collectAssertedOwnerSlots } from './resolveOwnershipAssertTarget'

/** Homeworld cluster envelopes: distinct outline colors (81 vs 162 LY). */
const HOMEWORLD_ENVELOPE_STROKE_BY_RADIUS_LY: Record<number, string> = {
  81: '#38bdf8',
  162: '#c084fc',
}

const HOMEWORLD_SECTOR_STROKE = '#fdba74'
const HOMEWORLD_ERROR_SECTOR_STROKE = '#fca5a5'
const HOMEWORLD_ASSERTED_SECTOR_STROKE = '#fbbf24'
const HOMEWORLD_SELECTED_SECTOR_STROKE = '#38bdf8'
/** Pinned (definite or asserted ownership): heavier outline. */
const HOMEWORLD_PINNED_SECTOR_STROKE_WIDTH = 2.25
/** Unpinned sectors: ~half the former default (1.5). */
const HOMEWORLD_UNPINNED_SECTOR_STROKE_WIDTH = 0.75
const HOMEWORLD_ENVELOPE_STROKE_WIDTH = 1.75

function homeworldEnvelopeStrokeColor(radiusLy: number): string {
  const rounded = Math.round(radiusLy)
  return HOMEWORLD_ENVELOPE_STROKE_BY_RADIUS_LY[rounded] ?? '#e2e8f0'
}

function homeworldEnvelopeDiskStrokes(
  overlay: MapRegionOverlay
): NonNullable<MapRegionOverlayPaint['diskStrokes']> {
  const disks =
    overlay.geometry.type === 'boundary' ? (overlay.geometry.disks ?? []) : []
  return disks.map((disk) => ({
    strokeColor: homeworldEnvelopeStrokeColor(disk.radius),
    strokeWidth: HOMEWORLD_ENVELOPE_STROKE_WIDTH,
  }))
}

/** True when any possible-owner member carries an asserted provenance kind. */
export function homeworldSectorHasAssertedOwnership(overlay: MapRegionOverlay): boolean {
  return collectAssertedOwnerSlots(overlay).length > 0
}

function homeworldSectorStrokeWidth(overlay: MapRegionOverlay): number {
  return overlay.isPinned === true
    ? HOMEWORLD_PINNED_SECTOR_STROKE_WIDTH
    : HOMEWORLD_UNPINNED_SECTOR_STROKE_WIDTH
}

/** Paint metadata for one homeworld sector overlay (stroke-only sectors + envelopes). */
export function homeworldSectorPaint(
  overlay: MapRegionOverlay,
  options?: { isSelected?: boolean }
): MapRegionOverlayPaint {
  const hasAssertedOwnership = homeworldSectorHasAssertedOwnership(overlay)
  const isSelected = options?.isSelected === true
  const diskStrokes = homeworldEnvelopeDiskStrokes(overlay)
  const baseStrokeWidth = homeworldSectorStrokeWidth(overlay)
  if (isSelected && hasAssertedOwnership) {
    return {
      fillOpacity: 0,
      boundaryStrokes: [
        {
          strokeColor: HOMEWORLD_ASSERTED_SECTOR_STROKE,
          strokeWidth: baseStrokeWidth,
        },
        {
          strokeColor: HOMEWORLD_SELECTED_SECTOR_STROKE,
          strokeWidth: 1.5,
          strokeDasharray: '2 2',
        },
      ],
      diskStrokes,
    }
  }
  let strokeColor =
    overlay.status === 'error' ? HOMEWORLD_ERROR_SECTOR_STROKE : HOMEWORLD_SECTOR_STROKE
  let strokeWidth = baseStrokeWidth
  if (hasAssertedOwnership) {
    strokeColor = HOMEWORLD_ASSERTED_SECTOR_STROKE
  }
  if (isSelected) {
    strokeColor = HOMEWORLD_SELECTED_SECTOR_STROKE
    strokeWidth = Math.max(strokeWidth, 2.5)
  }
  return {
    fillOpacity: 0,
    strokeColor,
    strokeWidth,
    diskStrokes,
  }
}

/** Paint metadata for planet-centered envelopes (disks only; no sector outline). */
export function homeworldPlanetEnvelopePaint(overlay: MapRegionOverlay): MapRegionOverlayPaint {
  return {
    fillOpacity: 0,
    diskStrokes: homeworldEnvelopeDiskStrokes(overlay),
  }
}

/**
 * Attach homeworld visual policy as paint metadata for the shared region blit.
 * Non-homeworld overlays pass through unchanged.
 */
export function applyHomeworldRegionStyle(
  overlays: readonly MapRegionOverlay[],
  options?: { selectedSectorIndex?: number | null }
): MapRegionOverlay[] {
  const selectedSectorIndex = options?.selectedSectorIndex ?? null
  return overlays.map((overlay) => {
    if (isHomeworldPlanetEnvelopeOverlay(overlay)) {
      return { ...overlay, paint: homeworldPlanetEnvelopePaint(overlay) }
    }
    if (!isHomeworldSectorOverlay(overlay)) return overlay
    const sectorMatch =
      selectedSectorIndex != null && overlay.id === `homeworld-sector-${selectedSectorIndex}`
    return {
      ...overlay,
      paint: homeworldSectorPaint(overlay, { isSelected: sectorMatch }),
    }
  })
}
