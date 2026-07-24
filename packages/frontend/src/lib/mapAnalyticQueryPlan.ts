import type {
  AnalyticItem,
  CombinedMapData,
  ConnectionsMapParams,
  MapDataResponse,
} from '../api/bff'
import { BASE_MAP_ANALYTIC_ID } from '../analytics/mapAnalyticIds'
import { isRegisteredMapAnalytic } from '../analytics/mapAnalyticRegistry'
import {
  combineMapData,
  type CombineMapDataOptionsBase,
} from '../analytics/mapLayers'

export { enabledMapAnalyticIds } from './enabledModeAnalyticIds'

/** Canonical base map analytic id when present in the analytics catalog. */
export function resolveBaseMapAnalyticId(analytics: AnalyticItem[]): string | null {
  return analytics.some((a) => a.id === BASE_MAP_ANALYTIC_ID) ? BASE_MAP_ANALYTIC_ID : null
}

/** Map data ids to fetch: base map first, then enabled selectable map analytics. */
export function mapIdsToFetch(analytics: AnalyticItem[], enabledMapIds: string[]): string[] {
  const base = resolveBaseMapAnalyticId(analytics)
  const withoutBase = enabledMapIds.filter((id) => id !== base)
  for (const analyticId of withoutBase) {
    if (!isRegisteredMapAnalytic(analyticId)) {
      throw new Error(`Map analytic "${analyticId}" is not registered in mapAnalyticRegistry`)
    }
  }
  if (base != null && !isRegisteredMapAnalytic(base)) {
    throw new Error(`Map analytic "${base}" is not registered in mapAnalyticRegistry`)
  }
  return base ? [base, ...withoutBase] : withoutBase
}

export type CombineMapDataFromQueriesInput = {
  liveConnectionsParams: ConnectionsMapParams | null
}

/** Builds merge options and combines per-analytic map query results in fetch order. */
export function combineMapDataFromAnalyticQueries(
  mapIds: readonly string[],
  mapQueryData: readonly (MapDataResponse | undefined)[],
  input: CombineMapDataFromQueriesInput
): CombinedMapData {
  const mergeOptions: CombineMapDataOptionsBase = {
    liveConnectionsParams: input.liveConnectionsParams,
  }
  return combineMapData(mapIds, mapQueryData, mergeOptions)
}
