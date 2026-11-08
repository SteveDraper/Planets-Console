import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../../api/bff'
import type {
  AnalyticShellScope,
  ScoresInferenceRowDetail,
  ScoresTableWithInferenceData,
  TableDataResponse,
} from '../../api/bff'
import { usePersistStoreHydrated } from '../../lib/usePersistStoreHydrated'
import { useAnalyticDiagnosticsStore } from '../../stores/analyticDiagnostics'
import { useScoresTablePreferencesStore } from '../../stores/scoresTablePreferences'
import { AnalyticTableGrid } from '../AnalyticTableGrid'
import type { ShellAnalyticTableViewProps } from '../shellAnalyticRegistry'
import { scoresAnalyticTableQueryKey } from './api'
import { scoresDiagnosticsFromTable } from './diagnosticsFromTable'
import { ScoresTableView } from './ScoresTableView'
import { useScoresShellStreamSession } from './scoresShellSession'
import { useGlobalInferencePause } from './useGlobalInferencePause'
import { useScoresInferenceByRow } from './useScoresInferenceByRow'

function buildScoresTableWithInference(
  data: TableDataResponse,
  inferenceByRow: ScoresInferenceRowDetail[]
): ScoresTableWithInferenceData {
  return {
    analyticId: data.analyticId,
    columns: data.columns,
    rows: data.rows,
    includeBuildInference: true,
    inferenceByRow,
  }
}

function ScoresAnalyticTableBody({
  analyticId,
  analyticScope,
  fetchEnabled,
}: {
  analyticId: string
  analyticScope: AnalyticShellScope
  fetchEnabled: boolean
}) {
  const scoresTableParams = useScoresTablePreferencesStore((s) => s.scoresTableParams)
  const setScoresDiagnostics = useAnalyticDiagnosticsStore((state) => state.setScoresDiagnostics)
  const { data, isPending, error } = useQuery({
    queryKey: scoresAnalyticTableQueryKey(analyticScope, scoresTableParams),
    queryFn: () => fetchAnalyticTable(analyticId, analyticScope),
    enabled: fetchEnabled,
  })
  const shellSession = useScoresShellStreamSession()
  const ownsStream = shellSession == null
  const inferenceEnabled =
    ownsStream &&
    scoresTableParams.includeBuildInference &&
    data?.buildInferenceAvailable !== false
  const buildInferenceAvailable = data == null ? undefined : data.buildInferenceAvailable !== false
  const globalInferencePauseEnabled =
    ownsStream &&
    fetchEnabled &&
    scoresTableParams.includeBuildInference &&
    buildInferenceAvailable === true
  const localInferencePause = useGlobalInferencePause(
    analyticScope,
    globalInferencePauseEnabled
  )
  const { inferenceByRow: localInferenceByRow } = useScoresInferenceByRow(
    data,
    analyticScope,
    inferenceEnabled && fetchEnabled,
    { onGlobalPauseChange: localInferencePause.syncPausedFromStream }
  )
  const inferenceByRow = shellSession?.inferenceByRow ?? localInferenceByRow
  const globalInferencePause = shellSession?.globalInferencePause ?? localInferencePause
  const scoresTableWithInference =
    data != null && inferenceByRow != null
      ? buildScoresTableWithInference(data, inferenceByRow)
      : null

  useEffect(() => {
    if (scoresTableWithInference != null) {
      setScoresDiagnostics(scoresDiagnosticsFromTable(scoresTableWithInference, analyticScope))
      return
    }
    setScoresDiagnostics(null)
  }, [analyticScope, scoresTableWithInference, setScoresDiagnostics])

  if (scoresTableWithInference != null) {
    return (
      <ScoresTableView
        data={scoresTableWithInference}
        analyticScope={analyticScope}
        isGloballyPaused={globalInferencePause.isGloballyPaused}
        globalInferencePause={globalInferencePause}
      />
    )
  }
  return <AnalyticTableGrid isPending={isPending} error={error} data={data} />
}

/** Scores table body. The shell owns the inference stream when it is mounted. */
export function ScoresAnalyticTableTile({
  analyticId,
  analyticScope,
  fetchEnabled,
}: ShellAnalyticTableViewProps) {
  const scoresPreferencesHydrated = usePersistStoreHydrated(useScoresTablePreferencesStore)
  const scoresFetchEnabled = fetchEnabled && scoresPreferencesHydrated

  if (analyticScope == null) {
    return (
      <div className="p-4 text-sm text-gray-400">
        Load game info and choose a turn and viewpoint to load this analytic.
      </div>
    )
  }

  return (
    <ScoresAnalyticTableBody
      analyticId={analyticId}
      analyticScope={analyticScope}
      fetchEnabled={scoresFetchEnabled}
    />
  )
}
