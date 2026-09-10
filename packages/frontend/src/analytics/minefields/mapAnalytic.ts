import type { MapAnalyticRegistration } from '../mapAnalyticRegistry'

/**
 * Minefields analytic: merge known-field facts into the combined map.
 * Type toggles and colors are applied at render time.
 */
export const minefieldsMapAnalytic: MapAnalyticRegistration = {
  mergeLayer(data, context) {
    const fields = data.minefields
    if (fields == null || fields.length === 0) return
    context.minefields.push(...fields)
  },
}
