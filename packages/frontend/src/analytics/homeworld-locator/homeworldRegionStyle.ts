import type { MapRegionOverlay, MapRegionOverlayPaint } from '../../api/mapRegionOverlayTypes'
import { PROVENANCE_KIND_ASSERTED } from './constants'
import { isHomeworldSectorOverlay } from './homeworldRegionDisplayMode'

/** Homeworld cluster envelopes: distinct outline colors (81 vs 162 LY). */
const HOMEWORLD_ENVELOPE_STROKE_BY_RADIUS_LY: Record<number, string> = {
  81: '#38bdf8',
  162: '#c084fc',
}

const HOMEWORLD_SECTOR_STROKE = '#fdba74'
const HOMEWORLD_ERROR_SECTOR_STROKE = '#fca5a5'
const HOMEWORLD_ASSERTED_SECTOR_STROKE = '#fbbf24'
const HOMEWORLD_SELECTED_SECTOR_STROKE = '#38bdf8'
const HOMEWORLD_SECTOR_STROKE_WIDTH = 1.5
const HOMEWORLD_ASSERTED_SECTOR_STROKE_WIDTH = 2.25
const HOMEWORLD_ENVELOPE_STROKE_WIDTH = 1.75

function homeworldEnvelopeStrokeColor(radiusLy: number): string {
  const rounded = Math.round(radiusLy)
  return HOMEWORLD_ENVELOPE_STROKE_BY_RADIUS_LY[rounded] ?? '#e2e8f0'
}

/** True when any possible-owner member carries an asserted provenance kind. */
export function homeworldSectorHasAssertedOwnership(overlay: MapRegionOverlay): boolean {
  const owners = overlay.possibleOwners ?? []
  return owners.some((owner) =>
    owner.provenanceKinds.some((kind) => kind === PROVENANCE_KIND_ASSERTED)
  )
}

/** Paint metadata for one homeworld sector overlay (stroke-only sectors + envelopes). */
export function homeworldSectorPaint(
  overlay: MapRegionOverlay,
  options?: { isSelected?: boolean }
): MapRegionOverlayPaint {
  const disks =
    overlay.geometry.type === 'boundary' ? (overlay.geometry.disks ?? []) : []
  const hasAssertedOwnership = homeworldSectorHasAssertedOwnership(overlay)
  const isSelected = options?.isSelected === true
  const diskStrokes = disks.map((disk) => ({
    strokeColor: homeworldEnvelopeStrokeColor(disk.radius),
    strokeWidth: HOMEWORLD_ENVELOPE_STROKE_WIDTH,
  }))
  if (isSelected && hasAssertedOwnership) {
    return {
      fillOpacity: 0,
      boundaryStrokes: [
        {
          strokeColor: HOMEWORLD_ASSERTED_SECTOR_STROKE,
          strokeWidth: HOMEWORLD_ASSERTED_SECTOR_STROKE_WIDTH,
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
  let strokeWidth = HOMEWORLD_SECTOR_STROKE_WIDTH
  if (hasAssertedOwnership) {
    strokeColor = HOMEWORLD_ASSERTED_SECTOR_STROKE
    strokeWidth = HOMEWORLD_ASSERTED_SECTOR_STROKE_WIDTH
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
    if (!isHomeworldSectorOverlay(overlay)) return overlay
    const sectorMatch =
      selectedSectorIndex != null && overlay.id === `homeworld-sector-${selectedSectorIndex}`
    return {
      ...overlay,
      paint: homeworldSectorPaint(overlay, { isSelected: sectorMatch }),
    }
  })
}
