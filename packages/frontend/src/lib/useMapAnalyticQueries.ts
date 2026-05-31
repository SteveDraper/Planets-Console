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
import {
  combineMapData,
  type CombineMapDataOptionsBase,
  type StellarCartographyMapMergeOptions,
} from '../analytics/mapLayers'

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

/** Merges per-analytic map payloads in fetch order. Pure; unit-tested separately. */
export function combineMapResultsFromQueries(
  mapIds: readonly string[],
  mapQueryData: readonly (MapDataResponse | undefined)[],
  mergeOptions: CombineMapDataOptionsBase
): CombinedMapData {
  return combineMapData(
    mapIds,
    mapQueryData.map((data) => ({ data })),
    mergeOptions
  )
}

// TanStack structural sharing reuses nested objects by reference; normalizeMapDataResponse
// clones node.planet snapshots so merged label fields are not dropped across refetches.
const MAP_QUERY_STRUCTURAL_SHARING = false as const

type MapAnalyticQueryContext = {
  analyticScope: AnalyticShellScope | null
  analyticFetchEnabled: boolean
  connectionsMapParams: ConnectionsMapParams
}

type MapAnalyticQuerySpec = {
  queryKey: readonly unknown[]
  queryFn: () => Promise<MapDataResponse>
  enabled: boolean
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

function defaultMapAnalyticQuerySpec(
  analyticId: string,
  context: MapAnalyticQueryContext
): MapAnalyticQuerySpec {
  return {
    queryKey: ['analytic', analyticId, 'map', context.analyticScope, 'planet-v2'] as const,
    queryFn: () => fetchAnalyticMap(analyticId, context.analyticScope!, undefined),
    enabled: context.analyticFetchEnabled,
  }
}

function connectionsMapAnalyticQuerySpec(context: MapAnalyticQueryContext): MapAnalyticQuerySpec {
  return {
    queryKey: connectionsMapQueryKey(context.analyticScope, context.connectionsMapParams),
    queryFn: () =>
      fetchAnalyticMap('connections', context.analyticScope!, context.connectionsMapParams),
    enabled: context.analyticFetchEnabled && context.analyticScope != null,
  }
}

/**
 * Map analytics whose BFF GET depends on UI params beyond shell scope (game, turn,
 * perspective). Each entry supplies a custom query key and fetch args so TanStack
 * refetches when those params change. Client-only merge options (e.g. Stellar
 * Cartography layer toggles) stay in `combineMapResultsFromQueries` -- no registry entry.
 * Expect more analytics here as map endpoints gain query parameters like Connections.
 */
const mapAnalyticQueryRegistry: Record<
  string,
  (context: MapAnalyticQueryContext) => MapAnalyticQuerySpec
> = {
  connections: connectionsMapAnalyticQuerySpec,
}

function mapAnalyticQuerySpecFor(
  analyticId: string,
  context: MapAnalyticQueryContext
): MapAnalyticQuerySpec {
  const builder = mapAnalyticQueryRegistry[analyticId]
  return builder ? builder(context) : defaultMapAnalyticQuerySpec(analyticId, context)
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

  const queryContext = useMemo(
    (): MapAnalyticQueryContext => ({
      analyticScope,
      analyticFetchEnabled,
      connectionsMapParams,
    }),
    [analyticScope, analyticFetchEnabled, connectionsMapParams]
  )

  const mapQueries = useQueries({
    queries: mapIds.map((analyticId) => {
      const spec = mapAnalyticQuerySpecFor(analyticId, queryContext)
      return {
        ...spec,
        structuralSharing: MAP_QUERY_STRUCTURAL_SHARING,
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

  const mapQueryData = mapQueries.map((q) => q.data)
  const combined = combineMapResultsFromQueries(mapIds, mapQueryData, mergeOptions)
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
