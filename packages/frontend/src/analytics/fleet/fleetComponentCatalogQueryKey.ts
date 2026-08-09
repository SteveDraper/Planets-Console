import type { AnalyticShellScope } from '../../api/bff'

export function fleetComponentCatalogQueryKey(analyticScope: AnalyticShellScope | null) {
  if (analyticScope == null) {
    return ['analytic', 'fleet', 'component-catalog', null] as const
  }
  return [
    'analytic',
    'fleet',
    'component-catalog',
    analyticScope.gameId,
    analyticScope.turn,
    analyticScope.perspective,
    analyticScope.username ?? null,
  ] as const
}
