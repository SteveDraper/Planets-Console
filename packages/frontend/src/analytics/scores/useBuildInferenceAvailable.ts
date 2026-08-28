import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable, type AnalyticShellScope } from '../../api/bff'
import { scoresTableQueryKey } from './api'

const AVAILABILITY_TABLE_PARAMS = { includeBuildInference: false } as const

export function useBuildInferenceAvailable(
  analyticScope: AnalyticShellScope | null,
  enabled: boolean
): boolean {
  const { data } = useQuery({
    queryKey: [
      'analytic',
      'scores',
      'table',
      analyticScope,
      ...scoresTableQueryKey(AVAILABILITY_TABLE_PARAMS),
    ] as const,
    queryFn: () => fetchAnalyticTable('scores', analyticScope!, AVAILABILITY_TABLE_PARAMS),
    enabled: enabled && analyticScope != null,
  })
  return data?.buildInferenceAvailable !== false
}
