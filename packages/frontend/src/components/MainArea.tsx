import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../api/bff'
import type {
  AnalyticItem,
  AnalyticShellScope,
  ConnectionsMapParams,
} from '../api/bff'
import { useStellarCartographyMapConfig } from '../lib/useStellarCartographyMapConfig'
import {
  DEFAULT_PLANET_LABEL_OPTIONS,
  type PlanetLabelOptions,
} from './planetMapLabelModel'
import { ShellCenterPane, ShellErrorPane } from './shell/ShellPlaceholders'
import { MapShellContent } from './shell/MapShellContent'
import { deriveTurnEnsureLoadingView } from '../lib/mapDisplayRetention'
import { errorDetailFromUnknown } from '../lib/queryRetry'
import { useMapAnalyticQueries } from '../lib/useMapAnalyticQueries'
import { useRetainedMapDisplay } from '../lib/useRetainedMapDisplay'

type ViewMode = 'tabular' | 'map'

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
  turnEnsureError: unknown | null | undefined
  /** Scope is set but login name is missing, so turn cannot be ensured. */
  turnBlockedNoLogin: boolean
  /** Parameters for the Connections map analytic (refetch when these change). */
  connectionsMapParams: ConnectionsMapParams
  /** Turns beyond latest stored game turn for ion storm prediction. */
  futureTurnOffset: number
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
}

function TableTile({
  analyticId,
  analyticScope,
  fetchEnabled,
}: {
  analyticId: string
  analyticScope: AnalyticShellScope | null
  fetchEnabled: boolean
}) {
  const { data, isPending, error } = useQuery({
    queryKey: ['analytic', analyticId, 'table', analyticScope] as const,
    queryFn: () => fetchAnalyticTable(analyticId, analyticScope!),
    enabled: fetchEnabled,
  })
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

/** Map queries and retention run only while this component is mounted (map view). */
function MapMainArea({
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

  const stellarCartography = useStellarCartographyMapConfig()

  const {
    enabledMapIds,
    mapIds,
    combined,
    pending,
    hasError,
    hasAnyData,
    mapQueries,
  } = useMapAnalyticQueries({
    enabledAnalyticIds,
    analytics,
    analyticScope,
    analyticFetchEnabled,
    connectionsMapParams,
    futureTurnOffset,
    stellarCartography,
  })

  const { mapShellView } = useRetainedMapDisplay({
    combined,
    gameId: analyticScope?.gameId ?? null,
    perspective: analyticScope?.perspective ?? null,
    turnDataReady,
    turnEnsurePending,
    mapPending: pending,
    mapHasError: hasError,
    mapHasAnyData: hasAnyData,
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

  return (
    <MapShellContent
      mapShellView={mapShellView}
      mapQueries={mapQueries}
      planetLabelOptions={planetLabelOptions}
      onPlanetLabelOptionsChange={onPlanetLabelOptionsChange}
      onMapZoomChange={onMapZoomChange}
      onSetZoomReady={onSetZoomReady}
      enabledMapIds={enabledMapIds}
      analyticScope={analyticScope}
    />
  )
}

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
      <main className="flex flex-1 flex-col gap-4 overflow-auto bg-black p-4">
        {enabledAnalyticIds.map((id) => (
          <section
            key={id}
            className="rounded-lg border border-[#52575d] bg-[#40454a] shadow-sm"
          >
            <h3 className="border-b border-[#52575d] px-4 py-2 text-sm font-medium text-slate-200">
              {analytics.find((a) => a.id === id)?.name ?? id}
            </h3>
            <TableTile
              analyticId={id}
              analyticScope={analyticScope}
              fetchEnabled={analyticFetchEnabled}
            />
          </section>
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

