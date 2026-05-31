import { useMemo } from 'react'
import { useQueries, type UseQueryResult } from '@tanstack/react-query'
import { fetchAnalyticMap } from '../api/bff'
import type {
  AnalyticItem,
  AnalyticShellScope,
  CombinedMapData,
  ConnectionsFlareMode,
  ConnectionsMapParams,
  MapDataResponse,
} from '../api/bff'
import { combineMapData, type StellarCartographyMapMergeOptions } from '../analytics/mapLayers'

export type ConnectionsMapQueryKey = readonly [
  'analytic',
  'connections',
  'map',
  string | null,
  number | null,
  number | null,
  number,
  boolean,
  ConnectionsFlareMode,
  number,
]

export type UseMapAnalyticQueriesInput = {
  enabledAnalyticIds: string[]
  analytics: AnalyticItem[]
  analyticScope: AnalyticShellScope | null
  analyticFetchEnabled: boolean
  connectionsMapParams: ConnectionsMapParams
  futureTurnOffset: number
  stellarCartography: StellarCartographyMapMergeOptions
}

export type UseMapAnalyticQueriesResult = {
  enabledMapIds: string[]
  mapIds: string[]
  combined: CombinedMapData
  pending: boolean
  hasError: boolean
  hasAnyData: boolean
  mapQueries: UseQueryResult<MapDataResponse, Error>[]
}

/** Id of the base map analytic (planets + edges), if present. */
export function baseMapId(analytics: AnalyticItem[]): string | null {
  const a = analytics.find((x) => x.type === 'base' && x.supportsMap)
  return a?.id ?? null
}

/** User-enabled analytic ids that support map view (selectable only). */
export function enabledMapAnalyticIds(
  enabledAnalyticIds: string[],
  analytics: AnalyticItem[]
): string[] {
  const set = new Set(
    analytics.filter((a) => a.supportsMap && a.type !== 'base').map((a) => a.id)
  )
  return enabledAnalyticIds.filter((id) => set.has(id))
}

/** Map data ids to fetch: base map first, then enabled selectable map analytics. */
export function mapIdsToFetch(analytics: AnalyticItem[], enabledMapIds: string[]): string[] {
  const base = baseMapId(analytics)
  const withoutBase = enabledMapIds.filter((id) => id !== base)
  return base ? [base, ...withoutBase] : withoutBase
}

/** Stable query key for the Connections map analytic. */
export function connectionsMapQueryKey(
  analyticScope: AnalyticShellScope | null,
  connectionsMapParams: ConnectionsMapParams
): ConnectionsMapQueryKey {
  return [
    'analytic',
    'connections',
    'map',
    analyticScope?.gameId ?? null,
    analyticScope?.turn ?? null,
    analyticScope?.perspective ?? null,
    connectionsMapParams.warpSpeed,
    connectionsMapParams.gravitonicMovement,
    connectionsMapParams.flareMode,
    connectionsMapParams.flareDepth,
  ]
}

export function useMapAnalyticQueries({
  enabledAnalyticIds,
  analytics,
  analyticScope,
  analyticFetchEnabled,
  connectionsMapParams,
  futureTurnOffset,
  stellarCartography,
}: UseMapAnalyticQueriesInput): UseMapAnalyticQueriesResult {
  const enabledMapIds = useMemo(
    () => enabledMapAnalyticIds(enabledAnalyticIds, analytics),
    [enabledAnalyticIds, analytics]
  )
  const mapIds = useMemo(
    () => mapIdsToFetch(analytics, enabledMapIds),
    [analytics, enabledMapIds]
  )

  const mapQueries = useQueries({
    queries: mapIds.map((analyticId) => {
      if (analyticId === 'connections') {
        return {
          queryKey: connectionsMapQueryKey(analyticScope, connectionsMapParams),
          queryFn: () => fetchAnalyticMap('connections', analyticScope!, connectionsMapParams),
          enabled: analyticFetchEnabled && analyticScope != null,
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
  const includesStellarCartography = mapIds.includes('stellar-cartography')

  const mergeOptions = useMemo(() => {
    const base = {
      liveConnectionsParams:
        mapIds.includes('connections') && analyticFetchEnabled ? connectionsMapParams : null,
      futureTurnOffset,
    }
    if (includesStellarCartography) {
      return { ...base, stellarCartography }
    }
    return base
  }, [
    mapIds,
    analyticFetchEnabled,
    connectionsMapParams,
    futureTurnOffset,
    includesStellarCartography,
    stellarCartography,
  ])

  const mapQueryResults = mapQueries.map((q) => q.data)

  const combined = useMemo(
    () =>
      combineMapData(
        mapIds,
        mapQueries.map((q) => ({ data: q.data })),
        mergeOptions
      ),
    [mapIds, mapQueryResults, mergeOptions]
  )
  const hasAnyData = mapQueries.some((q) => q.data != null)

  return {
    enabledMapIds,
    mapIds,
    combined,
    pending,
    hasError,
    hasAnyData,
    mapQueries,
  }
}
