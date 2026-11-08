import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../../api/bff'
import type { AnalyticShellScope } from '../../api/bff'
import { usePersistStoreHydrated } from '../../lib/usePersistStoreHydrated'
import { useScoresTablePreferencesStore } from '../../stores/scoresTablePreferences'
import { SCORES_ANALYTIC_ID, scoresAnalyticTableQueryKey } from './api'
import type { ScoresShellSession } from './scoresShellSession'
import { useGlobalInferencePause } from './useGlobalInferencePause'
import { useScoresInferenceByRow } from './useScoresInferenceByRow'

/**
 * Scoreboard inference session for an enabled scores row.
 * Build inference off leaves the session connected to nothing, including when
 * map mode greys the row and the table tile is unmounted.
 */
export function useScoresShellStream(
  analyticScope: AnalyticShellScope | null,
  enabled: boolean,
): ScoresShellSession {
  const scoresPreferencesHydrated = usePersistStoreHydrated(useScoresTablePreferencesStore)
  const scoresTableParams = useScoresTablePreferencesStore((state) => state.scoresTableParams)
  const streamEnabled =
    enabled && scoresPreferencesHydrated && scoresTableParams.includeBuildInference
  const { data } = useQuery({
    queryKey: scoresAnalyticTableQueryKey(analyticScope, scoresTableParams),
    queryFn: () => {
      if (analyticScope == null) {
        throw new Error('scores shell stream requires a scope')
      }
      return fetchAnalyticTable(SCORES_ANALYTIC_ID, analyticScope)
    },
    enabled: streamEnabled && analyticScope != null,
  })
  const inferenceEnabled = streamEnabled && data?.buildInferenceAvailable !== false
  const buildInferenceAvailable = data == null ? undefined : data.buildInferenceAvailable !== false
  const globalInferencePause = useGlobalInferencePause(
    analyticScope,
    streamEnabled && buildInferenceAvailable === true,
  )
  const { inferenceByRow } = useScoresInferenceByRow(
    data,
    analyticScope,
    inferenceEnabled,
    { onGlobalPauseChange: globalInferencePause.syncPausedFromStream },
  )
  return { inferenceByRow, globalInferencePause }
}
