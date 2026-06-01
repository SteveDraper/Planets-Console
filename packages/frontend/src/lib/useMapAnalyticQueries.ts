import { useCallback, useMemo } from 'react'
import { useQueries, type UseQueryResult } from '@tanstack/react-query'
import type {
  AnalyticItem,
  AnalyticShellScope,
  CombinedMapData,
  ConnectionsMapParams,
  MapDataResponse,
} from '../api/bff'
import {
  mapAnalyticQuerySpecFor,
  type MapAnalyticQueryContext,
} from '../analytics/mapAnalyticRegistry'
import {
  combineMapDataFromAnalyticQueries,
  enabledMapAnalyticIds,
  mapIdsToFetch,
} from './mapAnalyticQueryPlan'

export type UseMapAnalyticQueriesInput = {
  enabledAnalyticIds: string[]
  analytics: AnalyticItem[]
  analyticScope: AnalyticShellScope | null
  analyticFetchEnabled: boolean
  connectionsMapParams: ConnectionsMapParams
}

export type UseMapAnalyticQueriesResult = {
  enabledMapIds: string[]
  mapIds: string[]
  combined: CombinedMapData
  pending: boolean
  hasError: boolean
  hasAnyData: boolean
  mapError: unknown | null
  mapQueries: UseQueryResult<MapDataResponse, Error>[]
}

export function useMapAnalyticQueries({
  enabledAnalyticIds,
  analytics,
  analyticScope,
  analyticFetchEnabled,
  connectionsMapParams,
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

  const liveConnectionsParams = analyticFetchEnabled ? connectionsMapParams : null

  const combineMapQueries = useCallback(
    (results: UseQueryResult<MapDataResponse, Error>[]) => ({
      mapQueries: results,
      combined: combineMapDataFromAnalyticQueries(mapIds, results.map((q) => q.data), {
        liveConnectionsParams,
      }),
      pending: results.some((q) => q.isPending),
      hasError: results.some((q) => q.isError),
      hasAnyData: results.some((q) => q.data != null),
      mapError: results.find((q) => q.error)?.error ?? null,
    }),
    [mapIds, liveConnectionsParams]
  )

  const { mapQueries, combined, pending, hasError, hasAnyData, mapError } = useQueries({
    queries: mapIds.map((analyticId) => mapAnalyticQuerySpecFor(analyticId, queryContext)),
    combine: combineMapQueries,
  })

  return {
    enabledMapIds,
    mapIds,
    combined,
    pending,
    hasError,
    hasAnyData,
    mapError,
    mapQueries,
  }
}
