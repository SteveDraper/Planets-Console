import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
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
import { scoresDiagnosticsFromTable } from './diagnosticsFromTable'
import { ScoresTableView } from './ScoresTableView'
import { scoresAnalyticTableQueryOptions } from './scoresAnalyticTableQueryOptions'
import { useScoresShellStreamSession } from './scoresShellSession'

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
  analyticScope,
  fetchEnabled,
}: {
  analyticScope: AnalyticShellScope
  fetchEnabled: boolean
}) {
  const scoresTableParams = useScoresTablePreferencesStore((s) => s.scoresTableParams)
  const setScoresDiagnostics = useAnalyticDiagnosticsStore((state) => state.setScoresDiagnostics)
  const { data, isPending, error } = useQuery({
    ...scoresAnalyticTableQueryOptions(analyticScope, scoresTableParams),
    enabled: fetchEnabled,
  })
  const { inferenceByRow, globalInferencePause } = useScoresShellStreamSession()
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

/** Scores table body. The shell-lived stream owns the inference session. */
export function ScoresAnalyticTableTile({
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
      analyticScope={analyticScope}
      fetchEnabled={scoresFetchEnabled}
    />
  )
}
