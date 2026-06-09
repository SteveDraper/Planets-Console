import { memo, useEffect, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { cn } from '../lib/utils'
import { fetchAnalyticTable } from '../api/bff'
import type {
  AnalyticItem,
  AnalyticShellScope,
  ConnectionsMapParams,
  ScoresInferenceRowDetail,
  ScoresTableParams,
  ScoresTableWithInferenceData,
  TableDataResponse,
} from '../api/bff'
import { scoresTableQueryKey } from '../analytics/scores/api'
import { scoresDiagnosticsFromTable } from '../analytics/scores/diagnosticsFromTable'
import { ScoresTableView } from '../analytics/scores/ScoresTableView'
import { useScoresInferenceByRow } from '../analytics/scores/useScoresInferenceByRow'
import type { UseGlobalInferencePauseResult } from '../analytics/scores/useGlobalInferencePause'
import { useAnalyticDiagnosticsStore } from '../stores/analyticDiagnostics'
import { isStellarCartographyMapEnabled } from '../analytics/mapShellCartography'
import {
  DEFAULT_PLANET_LABEL_OPTIONS,
  type PlanetLabelOptions,
} from './planetMapLabelModel'
import { ShellCenterPane, ShellErrorPane } from './shell/ShellPlaceholders'
import { MapShellContent, type MapShellContentProps } from './shell/MapShellContent'
import { deriveTurnEnsureLoadingView } from '../lib/mapDisplayRetention'
import { errorDetailFromUnknown } from '../lib/queryRetry'
import { useMapAnalyticQueries } from '../lib/useMapAnalyticQueries'
import { useRetainedMapDisplay } from '../lib/useRetainedMapDisplay'
import { useStellarCartographyMapContext } from '../lib/useStellarCartographyMapContext'

type ViewMode = 'tabular' | 'map'

function AnalyticTableSection({ title, children }: { title: string; children: ReactNode }) {
  const [expanded, setExpanded] = useState(true)

  return (
    <section className="rounded-lg border border-[#52575d] bg-[#40454a] shadow-sm">
      <button
        type="button"
        aria-expanded={expanded}
        aria-label={expanded ? `Collapse ${title}` : `Expand ${title}`}
        onClick={() => setExpanded((value) => !value)}
        className={cn(
          'flex w-full items-center gap-2 px-4 py-2 text-left text-sm font-medium text-slate-200 transition-colors hover:bg-black/10 focus-visible:outline focus-visible:ring-1 focus-visible:ring-slate-500',
          expanded && 'border-b border-[#52575d]'
        )}
      >
        <ChevronDown
          className={cn(
            'h-4 w-4 shrink-0 text-slate-400 transition-transform duration-150',
            !expanded && '-rotate-90'
          )}
          aria-hidden
        />
        <span>{title}</span>
      </button>
      {expanded ? children : null}
    </section>
  )
}

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

type MainAreaProps = {
  viewMode: ViewMode
  enabledAnalyticIds: string[]
  analytics: AnalyticItem[]
  /** When null, tabular/map analytic data is not requested (missing game, turn, or perspective). */
  analyticScope: AnalyticShellScope | null
  /** When true, turn data for `analyticScope` is present in storage (ensure query succeeded). */
  turnDataReady: boolean
  turnEnsurePending: boolean
  turnEnsureIsError: boolean
  /** TanStack `error` for the turn-ensure query (shown inline when `turnEnsureIsError`). */
  turnEnsureError: unknown
  /** Scope is set but login name is missing, so turn cannot be ensured. */
  turnBlockedNoLogin: boolean
  /** Parameters for the Connections map analytic (refetch when these change). */
  connectionsMapParams: ConnectionsMapParams
  /** Parameters for the Scores table analytic (refetch when these change). */
  scoresTableParams: ScoresTableParams
  globalInferencePause: UseGlobalInferencePauseResult
  /** Turns beyond latest stored game turn for ion storm prediction. */
  futureTurnOffset: number
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
}

function TableTile({
  analyticId,
  analyticScope,
  fetchEnabled,
  scoresTableParams,
  globalInferencePause,
}: {
  analyticId: string
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
  scoresTableParams: ScoresTableParams
  globalInferencePause: UseGlobalInferencePauseResult
}) {
  const isScores = analyticId === 'scores'
  const inferenceEnabled = isScores && scoresTableParams.includeBuildInference
  const setScoresDiagnostics = useAnalyticDiagnosticsStore((state) => state.setScoresDiagnostics)
  const { data, isPending, error } = useQuery({
    queryKey: [
      'analytic',
      analyticId,
      'table',
      analyticScope,
      ...(isScores ? scoresTableQueryKey(scoresTableParams) : []),
    ] as const,
    queryFn: () =>
      fetchAnalyticTable(
        analyticId,
        analyticScope!,
        isScores ? scoresTableParams : undefined
      ),
    enabled: fetchEnabled,
  })
  const { inferenceByRow, resumeRow } = useScoresInferenceByRow(
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
    if (!isScores || analyticScope == null) {
      return
    }
    if (scoresTableWithInference != null) {
      setScoresDiagnostics(scoresDiagnosticsFromTable(scoresTableWithInference, analyticScope))
      return
    }
    setScoresDiagnostics(null)
  }, [isScores, analyticScope, scoresTableWithInference, setScoresDiagnostics])

  if (analyticScope == null) {
    return (
      <div className="p-4 text-sm text-gray-400">
        Load game info and choose a turn and viewpoint to load this analytic.
      </div>
    )
  }
  if (isPending) return <div className="p-4 text-sm text-gray-400">Loading…</div>
  if (error) {
    return (
      <div className="max-w-prose p-4 text-sm text-red-400 break-words">
        Error loading data. {errorDetailFromUnknown(error)}
      </div>
    )
  }
  if (!data) return null
  if (isScores && scoresTableWithInference != null) {
    return (
      <ScoresTableView
        data={scoresTableWithInference}
        analyticScope={analyticScope}
        onResumeRow={resumeRow}
        isGloballyPaused={globalInferencePause.isGloballyPaused}
        globalInferencePause={globalInferencePause}
      />
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

type MapMainAreaProps = {
  enabledAnalyticIds: string[]
  analytics: AnalyticItem[]
  analyticScope: AnalyticShellScope | null
  turnDataReady: boolean
  turnEnsurePending: boolean
  connectionsMapParams: ConnectionsMapParams
  futureTurnOffset: number
  planetLabelOptions: PlanetLabelOptions
  onPlanetLabelOptionsChange: (value: PlanetLabelOptions) => void
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
}

type MapShellContentBaseProps = Omit<MapShellContentProps, 'cartography'>

/** Subscribes to live Stellar Cartography UI when that analytic is enabled on the map. */
function MapShellContentWithCartography({
  analyticScope,
  ...props
}: MapShellContentBaseProps & { analyticScope: AnalyticShellScope }) {
  const cartography = useStellarCartographyMapContext(analyticScope)
  return <MapShellContent {...props} cartography={cartography} />
}

/** Map queries and retention run only while this component is mounted (map view). */
const MapMainArea = memo(function MapMainArea({
  enabledAnalyticIds,
  analytics,
  analyticScope,
  turnDataReady,
  turnEnsurePending,
  connectionsMapParams,
  futureTurnOffset,
  planetLabelOptions,
  onPlanetLabelOptionsChange,
  onMapZoomChange,
  onSetZoomReady,
}: MapMainAreaProps) {
  const analyticFetchEnabled = analyticScope != null && turnDataReady
  const mapQueries = useMapAnalyticQueries({
    enabledAnalyticIds,
    analytics,
    analyticScope,
    analyticFetchEnabled,
    connectionsMapParams,
  })

  const {
    enabledMapIds,
    mapIds,
    pending,
    hasError,
    hasAnyData,
    mapError,
  } = mapQueries

  const { mapShellView } = useRetainedMapDisplay({
    combined: mapQueries.combined,
    gameId: analyticScope?.gameId ?? null,
    perspective: analyticScope?.perspective ?? null,
    mapIds,
    turnDataReady,
    turnEnsurePending,
    mapPending: pending,
    mapHasError: hasError,
    mapHasAnyData: hasAnyData,
    mapError,
  })

  if (analyticScope == null) {
    return (
      <ShellCenterPane message="Load game info and choose a turn and viewpoint to load the map." />
    )
  }

  if (mapIds.length === 0) {
    return (
      <ShellCenterPane message="No base map available. Enable at least one map-capable analytic to see the map." />
    )
  }

  const shellProps: MapShellContentBaseProps = {
    mapShellView,
    futureTurnOffset,
    planetLabelOptions,
    onPlanetLabelOptionsChange,
    onMapZoomChange,
    onSetZoomReady,
  }

  if (isStellarCartographyMapEnabled(enabledMapIds)) {
    return <MapShellContentWithCartography {...shellProps} analyticScope={analyticScope} />
  }

  return <MapShellContent {...shellProps} cartography={undefined} />
})

export function MainArea({
  viewMode,
  enabledAnalyticIds,
  analytics,
  analyticScope,
  turnDataReady,
  turnEnsurePending,
  turnEnsureIsError,
  turnEnsureError,
  turnBlockedNoLogin,
  connectionsMapParams,
  scoresTableParams,
  globalInferencePause,
  futureTurnOffset,
  onMapZoomChange,
  onSetZoomReady,
}: MainAreaProps) {
  const analyticFetchEnabled = analyticScope != null && turnDataReady
  const [planetLabelOptions, setPlanetLabelOptions] = useState<PlanetLabelOptions>(
    DEFAULT_PLANET_LABEL_OPTIONS
  )

  if (viewMode === 'tabular' && enabledAnalyticIds.length === 0) {
    return <ShellCenterPane message="Enable at least one analytic in the left bar." />
  }

  if (analyticScope != null && turnBlockedNoLogin) {
    return (
      <ShellCenterPane message="Set login name in the header to load turn data for analytics." />
    )
  }

  if (analyticScope != null && !turnDataReady && turnEnsureIsError) {
    return (
      <ShellErrorPane
        title="Failed to load turn data"
        error={turnEnsureError}
        footer="See the error bar, or try another turn or viewpoint."
      />
    )
  }

  const turnEnsureLoading = deriveTurnEnsureLoadingView({
    hasAnalyticScope: analyticScope != null,
    turnDataReady,
    turnEnsurePending,
  })

  if (viewMode === 'tabular') {
    if (turnEnsureLoading.show) {
      return <ShellCenterPane message={turnEnsureLoading.loadingMessage} />
    }

    return (
      <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto bg-black p-4">
        {enabledAnalyticIds.map((id) => (
          <AnalyticTableSection
            key={id}
            title={analytics.find((a) => a.id === id)?.name ?? id}
          >
            <TableTile
              analyticId={id}
              analyticScope={analyticScope}
              fetchEnabled={analyticFetchEnabled}
              scoresTableParams={scoresTableParams}
              globalInferencePause={globalInferencePause}
            />
          </AnalyticTableSection>
        ))}
      </main>
    )
  }

  return (
    <MapMainArea
      enabledAnalyticIds={enabledAnalyticIds}
      analytics={analytics}
      analyticScope={analyticScope}
      turnDataReady={turnDataReady}
      turnEnsurePending={turnEnsurePending}
      connectionsMapParams={connectionsMapParams}
      futureTurnOffset={futureTurnOffset}
      planetLabelOptions={planetLabelOptions}
      onPlanetLabelOptionsChange={setPlanetLabelOptions}
      onMapZoomChange={onMapZoomChange}
      onSetZoomReady={onSetZoomReady}
    />
  )
}
