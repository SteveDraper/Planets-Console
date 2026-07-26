import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'

/** Kind emitted by Core for homeworld circular sector overlays. */
export const HOMEWORLD_SECTOR_KIND = 'homeworld-sector'

/**
 * Client preference for which homeworld sector overlays to paint.
 * Default is ``un-pinned`` (show non-pinned sectors only).
 */
export type HomeworldRegionDisplayMode = 'off' | 'un-pinned' | 'pinned' | 'all'

export const HOMEWORLD_REGION_DISPLAY_MODES: readonly HomeworldRegionDisplayMode[] = [
  'off',
  'un-pinned',
  'pinned',
  'all',
] as const

export const HOMEWORLD_REGION_DISPLAY_MODE_LABELS: Record<HomeworldRegionDisplayMode, string> = {
  off: 'Off',
  'un-pinned': 'Un-pinned',
  pinned: 'Pinned',
  all: 'All',
}

export function defaultHomeworldRegionDisplayMode(): HomeworldRegionDisplayMode {
  return 'un-pinned'
}

export function isHomeworldRegionDisplayMode(value: unknown): value is HomeworldRegionDisplayMode {
  return (
    value === 'off' || value === 'un-pinned' || value === 'pinned' || value === 'all'
  )
}

/** True when the overlay is a homeworld sector entry (display-mode owned). */
export function isHomeworldSectorOverlay(overlay: MapRegionOverlay): boolean {
  return overlay.kind === HOMEWORLD_SECTOR_KIND
}

/**
 * Filter ``regionOverlays`` by homeworld region display mode.
 * Non-homeworld overlays pass through unchanged.
 *
 * ``isPinned`` means the homeworld is determined and the owning player is known
 * (slot-anchored candidate). Orphan-only / empty sectors are un-pinned.
 */
export function applyHomeworldRegionDisplayMode(
  overlays: readonly MapRegionOverlay[],
  mode: HomeworldRegionDisplayMode
): MapRegionOverlay[] {
  if (mode === 'all') {
    return overlays.map((overlay) => overlay)
  }
  return overlays.filter((overlay) => {
    if (!isHomeworldSectorOverlay(overlay)) return true
    if (mode === 'off') return false
    const pinned = overlay.isPinned === true
    if (mode === 'pinned') return pinned
    // un-pinned
    return !pinned
  })
}
