import type { AnalyticShellScope } from '../../api/bff'

export function fleetTableQueryKey(analyticScope: AnalyticShellScope | null) {
  return ['analytic', 'fleet', 'table', analyticScope] as const
}
