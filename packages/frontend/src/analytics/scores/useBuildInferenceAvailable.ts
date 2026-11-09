import { useQuery } from '@tanstack/react-query'
import type { AnalyticShellScope } from '../../api/bff'
import type { ScoresTableParams } from './api'
import { scoresAnalyticTableQueryOptions } from './scoresAnalyticTableQueryOptions'

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
    ...scoresAnalyticTableQueryOptions(analyticScope, scoresTableParams),
    enabled: enabled && analyticScope != null,
  })
  if (!isSuccess) {
    return undefined
  }
  return data.buildInferenceAvailable !== false
}
