import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable } from '../api/bff'
import type {
  AnalyticItem,
  AnalyticShellScope,
  ConnectionsMapParams,
} from '../api/bff'
import { MapGraph } from './MapGraph'
import { useStellarCartographyMapConfig } from '../lib/useStellarCartographyMapConfig'
import { MapPaneWithDisplayControls } from './MapPaneWithDisplayControls'
import { PlanetMapInfoControls } from './PlanetMapInfoControls'
import {
  DEFAULT_PLANET_LABEL_OPTIONS,
  type PlanetLabelOptions,
} from './planetMapLabelModel'
import {
  MAP_SHELL_TURN_LOADING_MESSAGE,
  type MapShellView,
} from '../lib/mapDisplayRetention'
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
    const detail = error instanceof Error ? error.message : String(error)
    return (
      <div className="max-w-prose p-4 text-sm text-red-400 break-words">
        Error loading data. {detail}
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
    viewMode: 'map',
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
    viewMode: 'map',
    turnDataReady,
    turnEnsurePending,
    mapPending: pending,
    mapHasError: hasError,
    mapHasAnyData: hasAnyData,
  })

  if (analyticScope == null) {
    return (
      <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
        Load game info and choose a turn and viewpoint to load the map.
      </main>
    )
  }

  if (mapIds.length === 0) {
    return (
      <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
        No base map available. Enable at least one map-capable analytic to see the map.
      </main>
    )
  }

  return renderMapShellView(mapShellView, {
    mapQueries,
    planetLabelOptions,
    setPlanetLabelOptions: onPlanetLabelOptionsChange,
    onMapZoomChange,
    onSetZoomReady,
    pending,
    enabledMapIds,
    analyticScope,
  })
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
    return (
      <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
        Enable at least one analytic in the left bar.
      </main>
    )
  }

  if (analyticScope != null && turnBlockedNoLogin) {
    return (
      <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
        Set login name in the header to load turn data for analytics.
      </main>
    )
  }

  if (analyticScope != null && !turnDataReady && turnEnsureIsError) {
    const detail =
      turnEnsureError instanceof Error
        ? turnEnsureError.message
        : turnEnsureError != null
          ? String(turnEnsureError)
          : 'Unknown error'
    return (
      <main className="flex max-w-3xl flex-1 flex-col items-center justify-center gap-2 bg-black p-8 text-red-400">
        <p className="text-center font-medium">Failed to load turn data</p>
        <p className="whitespace-pre-wrap break-words text-left text-sm text-red-300/90">
          {detail}
        </p>
        <p className="text-center text-sm text-gray-500">
          See the error bar, or try another turn or viewpoint.
        </p>
      </main>
    )
  }

  if (viewMode === 'tabular') {
    if (analyticScope != null && !turnDataReady && turnEnsurePending) {
      return mapShellCenterMain(MAP_SHELL_TURN_LOADING_MESSAGE)
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

type RenderMapShellViewArgs = {
  mapQueries: { error: unknown }[]
  planetLabelOptions: PlanetLabelOptions
  setPlanetLabelOptions: (value: PlanetLabelOptions) => void
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
  pending: boolean
  enabledMapIds: string[]
  analyticScope: AnalyticShellScope | null
}

function renderMapShellView(
  mapShellView: MapShellView,
  {
    mapQueries,
    planetLabelOptions,
    setPlanetLabelOptions: onPlanetLabelOptionsChange,
    onMapZoomChange,
    onSetZoomReady,
    pending,
    enabledMapIds,
    analyticScope,
  }: RenderMapShellViewArgs
) {
  switch (mapShellView.phase) {
    case 'inactive':
      throw new Error('renderMapShellView called with inactive map shell view')
    case 'full-loading':
      return mapShellCenterMain(mapShellView.loadingMessage)
    case 'error': {
      const firstErr = mapQueries.find((q) => q.error)?.error
      const detail =
        firstErr instanceof Error
          ? firstErr.message
          : firstErr != null
            ? String(firstErr)
            : 'Failed to load map data'
      return mapShellErrorMain(detail)
    }
    case 'retained':
    case 'ready':
      return (
        <main className="relative flex min-h-0 flex-1 flex-col bg-black">
          <MapPaneWithDisplayControls
            controls={
              <PlanetMapInfoControls
                value={planetLabelOptions}
                onChange={onPlanetLabelOptionsChange}
              />
            }
          >
            <MapGraph
              data={mapShellView.displayMapData}
              className="h-full w-full min-h-0"
              onMapZoomChange={onMapZoomChange}
              onSetZoomReady={onSetZoomReady}
              planetLabelOptions={planetLabelOptions}
              stellarCartography={{
                sampleEnabled: enabledMapIds.includes('stellar-cartography'),
                analyticScope,
              }}
            />
          </MapPaneWithDisplayControls>
          <DeferredPendingMessage pending={mapShellView.phase === 'ready' && pending} />
        </main>
      )
  }
}

function mapShellCenterMain(message: string) {
  return (
    <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
      {message}
    </main>
  )
}

function mapShellErrorMain(detail: string) {
  return (
    <main className="flex max-w-3xl flex-1 flex-col items-center justify-center gap-2 bg-black p-8 text-red-400">
      <p className="text-center font-medium">Failed to load map data</p>
      <p className="whitespace-pre-wrap break-words text-left text-sm text-red-300/90">
        {detail}
      </p>
    </main>
  )
}

/** Shows "Loading additional map data…" after a short delay. Overlays the map so the pane size never changes. */
function DeferredPendingMessage({ pending }: { pending: boolean }) {
  const [show, setShow] = useState(false)
  useEffect(() => {
    let timeoutId: ReturnType<typeof setTimeout> | undefined

    if (pending) {
      timeoutId = setTimeout(() => setShow(true), 400)
    } else {
      // Reset `show` when no longer pending so a future pending state is delayed again.
      setShow(false)
    }

    return () => {
      if (timeoutId !== undefined) {
        clearTimeout(timeoutId)
      }
    }
  }, [pending])
  if (!pending || !show) return null
  return (
    <p className="pointer-events-none absolute inset-x-0 top-0 z-20 bg-black/90 px-4 py-1 text-sm text-gray-400">
      Loading additional map data…
    </p>
  )
}
