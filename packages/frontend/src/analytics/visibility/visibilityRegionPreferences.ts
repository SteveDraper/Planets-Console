import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  isVisibilityRegionKind,
  type VisibilityKindPreferences,
} from './kinds'

/** Filter disabled kinds and apply client color overrides for Visibility overlays. */
export function applyVisibilityRegionPreferences(
  overlays: readonly MapRegionOverlay[],
  preferences: VisibilityKindPreferences
): MapRegionOverlay[] {
  const result: MapRegionOverlay[] = []
  for (const overlay of overlays) {
    if (!isVisibilityRegionKind(overlay.kind)) {
      result.push(overlay)
      continue
    }
    const pref = preferences[overlay.kind]
    if (!pref.enabled) continue
    if (pref.fillColor === overlay.fillColor) {
      result.push(overlay)
      continue
    }
    result.push({ ...overlay, fillColor: pref.fillColor })
  }
  return result
}
