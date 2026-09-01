import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable, type AnalyticShellScope } from '../../api/bff'
import { scoresAnalyticTableQueryKey, type ScoresTableParams } from './api'

/**
 * Reads `buildInferenceAvailable` from the same Scores table query TableTile uses.
 * `undefined` until that query succeeds so Stealth cannot flash as available.
 */
export function useBuildInferenceAvailable(
  analyticScope: AnalyticShellScope | null,
  scoresTableParams: ScoresTableParams,
  enabled: boolean
): boolean | undefined {
  const { data, isSuccess } = useQuery({
    queryKey: scoresAnalyticTableQueryKey(analyticScope, scoresTableParams),
    queryFn: () => fetchAnalyticTable('scores', analyticScope!),
    enabled: enabled && analyticScope != null,
  })
  if (!isSuccess) {
    return undefined
  }
  return data.buildInferenceAvailable !== false
}
