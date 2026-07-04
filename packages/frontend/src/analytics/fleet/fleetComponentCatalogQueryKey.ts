import type { AnalyticShellScope } from '../../api/bff'

export function fleetComponentCatalogQueryKey(analyticScope: AnalyticShellScope | null) {
  return ['analytic', 'fleet', 'component-catalog', analyticScope] as const
}
