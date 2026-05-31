import { useMemo } from 'react'
import { useQueries, type UseQueryResult } from '@tanstack/react-query'
import type {
  AnalyticItem,
  AnalyticShellScope,
  CombinedMapData,
  ConnectionsMapParams,
  MapDataResponse,
} from '../api/bff'
import {
  combineMapData,
  type CombineMapDataOptionsBase,
  type StellarCartographyMapMergeOptions,
} from '../analytics/mapLayers'
import {
  mapAnalyticQuerySpecFor,
  mapIdsNeedLiveConnectionsParams,
  mapIdsNeedStellarCartographyMergeOptions,
  type MapAnalyticQueryContext,
} from '../analytics/mapAnalyticRegistry'

export type { ConnectionsMapQueryKey } from '../analytics/connections/mapAnalytic'
export { connectionsMapQueryKey } from '../analytics/connections/mapAnalytic'

export type UseMapAnalyticQueriesInput = {
  enabledAnalyticIds: string[]
  analytics: AnalyticItem[]
  analyticScope: AnalyticShellScope | null
  analyticFetchEnabled: boolean
  connectionsMapParams: ConnectionsMapParams
  futureTurnOffset: number
  /** Required when a registered map analytic needs Stellar Cartography merge options. */
  stellarCartography?: StellarCartographyMapMergeOptions
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

function buildMergeOptions(
  mapIds: readonly string[],
  analyticFetchEnabled: boolean,
  connectionsMapParams: ConnectionsMapParams,
  futureTurnOffset: number,
  stellarCartography: StellarCartographyMapMergeOptions | undefined
): CombineMapDataOptionsBase {
  const base: CombineMapDataOptionsBase = {
    liveConnectionsParams:
      mapIdsNeedLiveConnectionsParams(mapIds) && analyticFetchEnabled
        ? connectionsMapParams
        : null,
    futureTurnOffset,
  }
  if (mapIdsNeedStellarCartographyMergeOptions(mapIds)) {
    if (stellarCartography == null) {
      throw new Error('Stellar Cartography map merge requires stellarCartography options')
    }
    return { ...base, stellarCartography }
  }
  return base
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
    queries: mapIds.map((analyticId) => mapAnalyticQuerySpecFor(analyticId, queryContext)),
  })

  const pending = mapQueries.some((q) => q.isPending)
  const hasError = mapQueries.some((q) => q.error)

  const mergeOptions = useMemo(
    () =>
      buildMergeOptions(
        mapIds,
        analyticFetchEnabled,
        connectionsMapParams,
        futureTurnOffset,
        stellarCartography
      ),
    [mapIds, analyticFetchEnabled, connectionsMapParams, futureTurnOffset, stellarCartography]
  )

  const combineInputsKey = useMemo(
    () =>
      mapQueries
        .map(
          (q) =>
            `${q.dataUpdatedAt}:${q.data?.nodes.length ?? ''}:${q.data?.edges.length ?? ''}:${q.data?.overlayCircles?.length ?? ''}`
        )
        .join('|'),
    [mapQueries]
  )

  const combined = useMemo(
    () =>
      combineMapResultsFromQueries(
        mapIds,
        mapQueries.map((q) => q.data),
        mergeOptions
      ),
    // combineInputsKey tracks query data versions; mapQueries read from render closure.
    [mapIds, mergeOptions, combineInputsKey]
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
