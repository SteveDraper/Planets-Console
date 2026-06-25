import type { MapAnalyticQueryContext, MapAnalyticRegistration } from '../mapAnalyticRegistry'
import { FLEET_ANALYTIC_ID } from '../mapAnalyticIds'

/**
 * Scaffold registration so enabling Fleet in map view does not crash the shell.
 * Node merge, visibility filter, and fleet map wire parsing land in #128.
 */
export const fleetMapAnalytic: MapAnalyticRegistration = {
  buildQuerySpec(context: MapAnalyticQueryContext) {
    return {
      queryKey: [
        'analytic',
        FLEET_ANALYTIC_ID,
        'map',
        context.analyticScope,
        'scaffold-v0',
      ] as const,
      queryFn: async () => ({ analyticId: FLEET_ANALYTIC_ID, nodes: [], edges: [] }),
      enabled: false,
    }
  },
  mergeLayer() {
    // Fleet map layer merge is implemented in #128.
  },
}
