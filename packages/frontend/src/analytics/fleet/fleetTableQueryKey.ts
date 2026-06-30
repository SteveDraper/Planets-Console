import type { AnalyticShellScope } from '../../api/bff'

export function fleetTableQueryKey(
  analyticScope: AnalyticShellScope | null,
  scoresInferenceRevision: number
) {
  return ['analytic', 'fleet', 'table', analyticScope, scoresInferenceRevision] as const
}
