import { queryOptions } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../../api/bff'
import type { AnalyticShellScope } from '../../api/bff'
import { SCORES_ANALYTIC_ID, scoresAnalyticTableQueryKey, type ScoresTableParams } from './api'

/**
 * The one definition of the Scores table GET query. The table tile, the shell
 * stream, and the build inference availability read share its cache entry.
 * Callers add their own `enabled`.
 */
export function scoresAnalyticTableQueryOptions(
  analyticScope: AnalyticShellScope | null,
  scoresParams: ScoresTableParams
) {
  return queryOptions({
    queryKey: scoresAnalyticTableQueryKey(analyticScope, scoresParams),
    queryFn: () => {
      if (analyticScope == null) {
        throw new Error('scores table query requires a scope')
      }
      return fetchAnalyticTable(SCORES_ANALYTIC_ID, analyticScope)
    },
  })
}
