import { useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable, fetchAnalyticMap } from '../api/bff'
import type {
  AnalyticItem,
  AnalyticShellScope,
  ConnectionsFlareMode,
  ConnectionsMapParams,
  MapDataResponse,
} from '../api/bff'
import { combineMapData } from '../analytics/mapLayers'
import { MapGraph } from './MapGraph'
import { MapPaneWithDisplayControls } from './MapPaneWithDisplayControls'
import { PlanetMapInfoControls } from './PlanetMapInfoControls'
import {
  DEFAULT_PLANET_LABEL_OPTIONS,
  type PlanetLabelOptions,
} from './planetMapLabelModel'

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

/** Id of the base map analytic (planets + edges), if present. */
function baseMapId(analytics: AnalyticItem[]): string | null {
  const a = analytics.find((x) => x.type === 'base' && x.supportsMap)
  return a?.id ?? null
}

/** User-enabled analytic ids that support map view (selectable only). */
function enabledMapAnalyticIds(
  enabledAnalyticIds: string[],
  analytics: AnalyticItem[]
): string[] {
  const set = new Set(
    analytics.filter((a) => a.supportsMap && a.type !== 'base').map((a) => a.id)
  )
  return enabledAnalyticIds.filter((id) => set.has(id))
}

/** Map data ids to fetch: base map first, then enabled selectable map analytics. */
function mapIdsToFetch(analytics: AnalyticItem[], enabledMapIds: string[]): string[] {
  const base = baseMapId(analytics)
  const withoutBase = enabledMapIds.filter((id) => id !== base)
  return base ? [base, ...withoutBase] : withoutBase
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
  onMapZoomChange,
  onSetZoomReady,
}: MainAreaProps) {
  const analyticFetchEnabled = analyticScope != null && turnDataReady

  const enabledMapIds = useMemo(
    () => enabledMapAnalyticIds(enabledAnalyticIds, analytics),
    [enabledAnalyticIds, analytics]
  )
  const mapIds = useMemo(
    () => (viewMode === 'map' ? mapIdsToFetch(analytics, enabledMapIds) : []),
    [viewMode, analytics, enabledMapIds]
  )

  const mapQueries = useQueries({
    queries: mapIds.map((analyticId) => {
      if (analyticId === 'connections') {
        const queryKey =
          analyticScope != null
            ? ([
                'analytic',
                'connections',
                'map',
                analyticScope.gameId,
                analyticScope.turn,
                analyticScope.perspective,
                connectionsMapParams.warpSpeed,
                connectionsMapParams.gravitonicMovement,
                connectionsMapParams.flareMode,
                connectionsMapParams.flareDepth,
              ] as const)
            : ([
                'analytic',
                'connections',
                'map',
                'idle',
                0,
                0,
                connectionsMapParams.warpSpeed,
                connectionsMapParams.gravitonicMovement,
                connectionsMapParams.flareMode,
                connectionsMapParams.flareDepth,
              ] as const)
        return {
          queryKey,
          queryFn: async ({ queryKey: qk }) => {
            if (qk[3] === 'idle') {
              return {
                analyticId: 'connections',
                nodes: [],
                edges: [],
                routes: [],
              } satisfies MapDataResponse
            }
            const [, , , gameId, turn, perspective, warpSpeed, gravitonicMovement, flareMode, flareDepth] =
              qk
            const scope: AnalyticShellScope = {
              gameId: String(gameId),
              turn: Number(turn),
              perspective: Number(perspective),
            }
            const params: ConnectionsMapParams = {
              warpSpeed: Number(warpSpeed),
              gravitonicMovement: Boolean(gravitonicMovement),
              flareMode: flareMode as ConnectionsFlareMode,
              flareDepth: Number(flareDepth) as ConnectionsMapParams['flareDepth'],
            }
            return fetchAnalyticMap('connections', scope, params)
          },
          enabled: analyticFetchEnabled,
          placeholderData: undefined,
          structuralSharing: false as const,
        }
      }
      return {
        queryKey: ['analytic', analyticId, 'map', analyticScope, 'planet-v2'] as const,
        queryFn: () => fetchAnalyticMap(analyticId, analyticScope!, undefined),
        enabled: analyticFetchEnabled,
        structuralSharing: false as const,
      }
    }),
  })
  const pending = mapQueries.some((q) => q.isPending)
  const hasError = mapQueries.some((q) => q.error)
  const mapQueriesStateSignature = mapQueries
    .map((q) => `${q.dataUpdatedAt}:${q.fetchStatus}:${q.status}`)
    .join('|')
  const mapWellCellCount = mapQueries.reduce((total, q) => {
    const nodes = q.data?.nodes
    if (!nodes) return total
    return total + nodes.reduce((sum, node) => sum + (node.normalWellCells?.length ?? 0), 0)
  }, 0)
  const liveConnectionsParams =
    mapIds.includes('connections') && analyticFetchEnabled ? connectionsMapParams : null
  const mapIdsKey = mapIds.join('\0')
  const combined = useMemo(
    () =>
      combineMapData(
        mapIds,
        mapQueries.map((q) => ({ data: q.data })),
        liveConnectionsParams
      ),
    [
      mapIdsKey,
      mapQueriesStateSignature,
      mapWellCellCount,
      liveConnectionsParams,
      analyticFetchEnabled,
      connectionsMapParams.flareMode,
      connectionsMapParams.warpSpeed,
      connectionsMapParams.gravitonicMovement,
      connectionsMapParams.flareDepth,
    ]
  )
  const hasAnyData = mapQueries.some((q) => q.data != null)

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

  if (analyticScope != null && !turnDataReady && turnEnsurePending) {
    return (
      <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
        Loading turn data…
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

  if (viewMode === 'map' && analyticScope == null) {
    return (
      <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
        Load game info and choose a turn and viewpoint to load the map.
      </main>
    )
  }

  if (viewMode === 'map' && mapIds.length === 0) {
    return (
      <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
        No base map available. Enable at least one map-capable analytic to see the map.
      </main>
    )
  }
  // Only show loading when we have no data yet (initial load). While adding another analytic,
  // keep rendering the map with current data so React Flow stays mounted and viewport is preserved.
  if (!hasAnyData && pending) {
    return (
      <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
        Loading map…
      </main>
    )
  }
  if (hasError && !hasAnyData) {
    const firstErr = mapQueries.find((q) => q.error)?.error
    const detail =
      firstErr instanceof Error
        ? firstErr.message
        : firstErr != null
          ? String(firstErr)
          : 'Failed to load map data'
    return (
      <main className="flex max-w-3xl flex-1 flex-col items-center justify-center gap-2 bg-black p-8 text-red-400">
        <p className="text-center font-medium">Failed to load map data</p>
        <p className="whitespace-pre-wrap break-words text-left text-sm text-red-300/90">
          {detail}
        </p>
      </main>
    )
  }

  return (
    <main className="flex min-h-0 flex-1 flex-col bg-black">
      <DeferredPendingMessage pending={pending} />
      <MapPaneWithDisplayControls
        controls={
          <PlanetMapInfoControls value={planetLabelOptions} onChange={setPlanetLabelOptions} />
        }
      >
        <MapGraph
          data={combined}
          className="h-full w-full min-h-0"
          onMapZoomChange={onMapZoomChange}
          onSetZoomReady={onSetZoomReady}
          planetLabelOptions={planetLabelOptions}
        />
      </MapPaneWithDisplayControls>
    </main>
  )
}

/** Shows "Loading additional map data…" only after a short delay so it doesn't flash on first map load. */
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
    <p className="shrink-0 bg-black px-4 py-1 text-sm text-gray-400">
      Loading additional map data…
    </p>
  )
}
