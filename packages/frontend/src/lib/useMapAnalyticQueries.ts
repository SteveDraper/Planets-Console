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
import {
  formatMapLayerErrorBanner,
  type MapLayerFailure,
} from './formatMapLayerErrorBanner'

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
  mapError: unknown
  mapQueries: UseQueryResult<MapDataResponse, Error>[]
}

function analyticNameById(
  analytics: AnalyticItem[],
  analyticId: string
): string | undefined {
  return analytics.find((row) => row.id === analyticId)?.name
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
    (results: UseQueryResult<MapDataResponse, Error>[]) => {
      const failures: MapLayerFailure[] = []
      for (let index = 0; index < results.length; index += 1) {
        const result = results[index]
        const analyticId = mapIds[index]
        if (result == null || analyticId == null || !result.isError || result.error == null) {
          continue
        }
        failures.push({
          analyticId,
          analyticName: analyticNameById(analytics, analyticId),
          error: result.error,
        })
      }
      return {
        mapQueries: results,
        combined: combineMapDataFromAnalyticQueries(mapIds, results.map((q) => q.data), {
          liveConnectionsParams,
        }),
        pending: results.some((q) => q.isPending),
        hasError: failures.length > 0,
        hasAnyData: results.some((q) => q.data != null),
        mapError:
          failures.length > 0 ? new Error(formatMapLayerErrorBanner(failures)) : null,
      }
    },
    [mapIds, liveConnectionsParams, analytics]
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
