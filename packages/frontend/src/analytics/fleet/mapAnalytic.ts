import type { MapAnalyticQueryContext, MapAnalyticRegistration } from '../mapAnalyticRegistry'
import { FLEET_ANALYTIC_ID } from '../mapAnalyticIds'

/**
 * Fleet map registration for enablement / catalog symmetry.
 * Live paint is stream-backed location rings (ADR 0011); mergeLayer stays a no-op.
 */
export const fleetMapAnalytic: MapAnalyticRegistration = {
  buildQuerySpec(context: MapAnalyticQueryContext) {
    return {
      queryKey: [
        'analytic',
        FLEET_ANALYTIC_ID,
        'map',
        context.analyticScope,
        'stream-rings-v1',
      ] as const,
      queryFn: async () => ({ analyticId: FLEET_ANALYTIC_ID, nodes: [], edges: [] }),
      enabled: context.analyticFetchEnabled && context.analyticScope != null,
    }
  },
  mergeLayer() {
    // Location rings paint from the fleet stream overlay, not map REST geometry.
  },
}
