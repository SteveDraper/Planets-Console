import type { MapRegionOverlay, MapRegionOverlayPaint } from '../../api/mapRegionOverlayTypes'
import { isHomeworldSectorOverlay } from './homeworldRegionDisplayMode'

/** Homeworld cluster envelopes: distinct outline colors (81 vs 162 LY). */
const HOMEWORLD_ENVELOPE_STROKE_BY_RADIUS_LY: Record<number, string> = {
  81: '#38bdf8',
  162: '#c084fc',
}

const HOMEWORLD_SECTOR_STROKE = '#fdba74'
const HOMEWORLD_ERROR_SECTOR_STROKE = '#fca5a5'
const HOMEWORLD_SECTOR_STROKE_WIDTH = 1.5
const HOMEWORLD_ENVELOPE_STROKE_WIDTH = 1.75

function homeworldEnvelopeStrokeColor(radiusLy: number): string {
  const rounded = Math.round(radiusLy)
  return HOMEWORLD_ENVELOPE_STROKE_BY_RADIUS_LY[rounded] ?? '#e2e8f0'
}

/** Paint metadata for one homeworld sector overlay (stroke-only sectors + envelopes). */
export function homeworldSectorPaint(overlay: MapRegionOverlay): MapRegionOverlayPaint {
  const disks =
    overlay.geometry.type === 'boundary' ? (overlay.geometry.disks ?? []) : []
  return {
    fillOpacity: 0,
    strokeColor:
      overlay.status === 'error' ? HOMEWORLD_ERROR_SECTOR_STROKE : HOMEWORLD_SECTOR_STROKE,
    strokeWidth: HOMEWORLD_SECTOR_STROKE_WIDTH,
    diskStrokes: disks.map((disk) => ({
      strokeColor: homeworldEnvelopeStrokeColor(disk.radius),
      strokeWidth: HOMEWORLD_ENVELOPE_STROKE_WIDTH,
    })),
  }
}

/**
 * Attach homeworld visual policy as paint metadata for the shared region blit.
 * Non-homeworld overlays pass through unchanged.
 */
export function applyHomeworldRegionStyle(
  overlays: readonly MapRegionOverlay[]
): MapRegionOverlay[] {
  return overlays.map((overlay) => {
    if (!isHomeworldSectorOverlay(overlay)) return overlay
    return { ...overlay, paint: homeworldSectorPaint(overlay) }
  })
}
