import type { MapAnalyticRegistration } from '../mapAnalyticRegistry'
import { MAP_REGION_DEMO_ANALYTIC_ID } from '../mapAnalyticIds'

/**
 * Temporary demo analytic: merge Core hybrid ``regionOverlays`` into the combined map.
 * Remove when the Visibility analytic lands.
 */
export const mapRegionDemoMapAnalytic: MapAnalyticRegistration = {
  mergeLayer(data, context) {
    const overlays = data.regionOverlays
    if (overlays == null || overlays.length === 0) return
    context.regionOverlays.push(...overlays)
  },
}

export { MAP_REGION_DEMO_ANALYTIC_ID }
