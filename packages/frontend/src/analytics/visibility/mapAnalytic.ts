import type { MapAnalyticRegistration } from '../mapAnalyticRegistry'

/**
 * Visibility analytic: merge Core hybrid ``regionOverlays`` into the combined map.
 * Client kind toggles and colors are applied at render time.
 */
export const visibilityMapAnalytic: MapAnalyticRegistration = {
  mergeLayer(data, context) {
    const overlays = data.regionOverlays
    if (overlays == null || overlays.length === 0) return
    context.regionOverlays.push(...overlays)
  },
}
