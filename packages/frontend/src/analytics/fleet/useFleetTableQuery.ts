import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../../api/bff'
import type { AnalyticShellScope } from '../../api/bff'
import { useScoresInferenceRevision } from '../../shell/scoresInferenceRevision'
import { fleetTableQueryKey } from './fleetTableQueryKey'

export function useFleetTableQuery(
  analyticScope: AnalyticShellScope | null,
  fetchEnabled: boolean
) {
  const scoresInferenceRevision = useScoresInferenceRevision(analyticScope)

  return useQuery({
    queryKey: fleetTableQueryKey(analyticScope, scoresInferenceRevision),
    queryFn: () => fetchAnalyticTable('fleet', analyticScope!),
    enabled: fetchEnabled && analyticScope != null,
  })
}
