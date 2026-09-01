import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../../api/bff'
import type {
  AnalyticShellScope,
  ScoresInferenceRowDetail,
  ScoresTableWithInferenceData,
  TableDataResponse,
} from '../../api/bff'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import { usePersistStoreHydrated } from '../../lib/usePersistStoreHydrated'
import { useAnalyticDiagnosticsStore } from '../../stores/analyticDiagnostics'
import { useScoresTablePreferencesStore } from '../../stores/scoresTablePreferences'
import type { ShellAnalyticTableViewProps } from '../shellAnalyticRegistry'
import { scoresAnalyticTableQueryKey } from './api'
import { scoresDiagnosticsFromTable } from './diagnosticsFromTable'
import { ScoresTableView } from './ScoresTableView'
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
  analyticScope,
  fetchEnabled,
}: {
  analyticScope: AnalyticShellScope
  fetchEnabled: boolean
}) {
  const scoresTableParams = useScoresTablePreferencesStore((s) => s.scoresTableParams)
  const setScoresDiagnostics = useAnalyticDiagnosticsStore((state) => state.setScoresDiagnostics)
  const { data, isPending, error } = useQuery({
    queryKey: scoresAnalyticTableQueryKey(analyticScope, scoresTableParams),
    queryFn: () => fetchAnalyticTable('scores', analyticScope),
    enabled: fetchEnabled,
  })
  const inferenceEnabled =
    scoresTableParams.includeBuildInference && data?.buildInferenceAvailable !== false
  const buildInferenceAvailable = data == null ? undefined : data.buildInferenceAvailable !== false
  const globalInferencePauseEnabled =
    fetchEnabled &&
    scoresTableParams.includeBuildInference &&
    buildInferenceAvailable === true
  const globalInferencePause = useGlobalInferencePause(
    analyticScope,
    globalInferencePauseEnabled
  )
  const { inferenceByRow } = useScoresInferenceByRow(
    data,
    analyticScope,
    inferenceEnabled && fetchEnabled,
    { onGlobalPauseChange: globalInferencePause.syncPausedFromStream }
  )
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

  if (isPending) return <div className="p-4 text-sm text-gray-400">Loading…</div>
  if (error) {
    return (
      <div className="max-w-prose p-4 text-sm text-red-400 break-words">
        Error loading data. {errorDetailFromUnknown(error)}
      </div>
    )
  }
  if (!data) return null
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
  if (!Array.isArray(data.columns) || !Array.isArray(data.rows)) {
    return (
      <div className="p-4 text-sm text-gray-400">This analytic has no tabular grid view.</div>
    )
  }
  return (
    <div className="overflow-auto">
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-[#52575d]">
            {data.columns.map((c) => (
              <th key={c} className="px-3 py-2 text-left font-medium text-slate-200">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr key={i} className="border-b border-[#52575d]/60">
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-2 text-gray-400">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Scores table body: REST grid plus tile-lived inference stream. */
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
