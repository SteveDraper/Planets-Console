import { useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { fetchAnalyticTable, fetchAnalyticMap } from '../api/bff'
import type { AnalyticItem, CombinedMapData, MapDataResponse } from '../api/bff'
import { MapGraph } from './MapGraph'

type ViewMode = 'tabular' | 'map'

function combineMapData(
  analyticIds: string[],
  results: { data?: MapDataResponse }[]
): CombinedMapData {
  const nodes: CombinedMapData['nodes'] = []
  const edges: CombinedMapData['edges'] = []
  results.forEach((result, idx) => {
    const data = result.data
    const prefix = analyticIds[idx] ?? ''
    if (!data) return
    data.nodes.forEach((n) => {
      nodes.push({ id: `${prefix}:${n.id}`, label: n.label, x: n.x, y: n.y })
    })
    data.edges.forEach((e) => {
      edges.push({
        source: `${prefix}:${e.source}`,
        target: `${prefix}:${e.target}`,
      })
    })
  })
  return { nodes, edges }
}

type MainAreaProps = {
  viewMode: ViewMode
  enabledAnalyticIds: string[]
  analytics: AnalyticItem[]
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
}

function TableTile({ analyticId }: { analyticId: string }) {
  const { data, isPending, error } = useQuery({
    queryKey: ['analytic', analyticId, 'table'],
    queryFn: () => fetchAnalyticTable(analyticId),
  })
  if (isPending) return <div className="p-4 text-sm text-gray-400">Loading…</div>
  if (error) return <div className="p-4 text-sm text-red-400">Error loading data</div>
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
  onMapZoomChange,
  onSetZoomReady,
}: MainAreaProps) {
  const enabledMapIds = useMemo(
    () => enabledMapAnalyticIds(enabledAnalyticIds, analytics),
    [enabledAnalyticIds, analytics]
  )
  const mapIds = useMemo(
    () => (viewMode === 'map' ? mapIdsToFetch(analytics, enabledMapIds) : []),
    [viewMode, analytics, enabledMapIds]
  )

  const mapQueries = useQueries({
    queries: mapIds.map((analyticId) => ({
      queryKey: ['analytic', analyticId, 'map'] as const,
      queryFn: () => fetchAnalyticMap(analyticId),
    })),
  })
  const pending = mapQueries.some((q) => q.isPending)
  const hasError = mapQueries.some((q) => q.error)
  const mapQueryData = mapQueries.map((q) => q.data)
  const combined = useMemo(
    () => combineMapData(mapIds, mapQueryData.map((data) => ({ data }))),
    [mapIds, ...mapQueryData]
  )
  const hasAnyData = mapQueries.some((q) => q.data != null)

  if (viewMode === 'tabular' && enabledAnalyticIds.length === 0) {
    return (
      <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
        Enable at least one analytic in the left bar.
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
              Analytic: {id}
            </h3>
            <TableTile analyticId={id} />
          </section>
        ))}
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
    return (
      <main className="flex flex-1 items-center justify-center bg-black p-8 text-red-400">
        Failed to load map data
      </main>
    )
  }

  return (
    <main className="flex min-h-0 flex-1 flex-col bg-black">
      <DeferredPendingMessage pending={pending} />
      <MapGraph
        data={combined}
        className="h-full w-full min-h-0"
        onMapZoomChange={onMapZoomChange}
        onSetZoomReady={onSetZoomReady}
      />
    </main>
  )
}

/** Shows "Loading additional map data…" only after a short delay so it doesn't flash on first map load. */
function DeferredPendingMessage({ pending }: { pending: boolean }) {
  const [show, setShow] = useState(false)
  useEffect(() => {
    if (!pending) {
      setShow(false)
      return
    }
    const t = setTimeout(() => setShow(true), 400)
    return () => clearTimeout(t)
  }, [pending])
  if (!pending || !show) return null
  return (
    <p className="shrink-0 bg-black px-4 py-1 text-sm text-gray-400">
      Loading additional map data…
    </p>
  )
}
