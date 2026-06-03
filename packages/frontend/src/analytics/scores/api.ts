import type { AnalyticShellScope } from '../../api/bff'

/** Wire query names for Scores table GETs. */
export const SCORES_QUERY_WIRE = {
  includeBuildInference: 'includeBuildInference',
} as const

/** Query parameters for the Scores table analytic (BFF forwards to Core). */
export type ScoresTableParams = {
  includeBuildInference: boolean
}

export function appendScoresTableQueryParams(
  params: URLSearchParams,
  scoresParams: ScoresTableParams
): void {
  if (scoresParams.includeBuildInference) {
    params.set(SCORES_QUERY_WIRE.includeBuildInference, 'true')
  }
}

export function scoresTableQueryKey(scoresParams: ScoresTableParams): readonly [boolean] {
  return [scoresParams.includeBuildInference] as const
}

export function scoresRowInferenceQueryKey(
  scope: AnalyticShellScope,
  playerId: number
): readonly ['analytic', 'scores', 'inference', AnalyticShellScope, number] {
  return ['analytic', 'scores', 'inference', scope, playerId] as const
}
