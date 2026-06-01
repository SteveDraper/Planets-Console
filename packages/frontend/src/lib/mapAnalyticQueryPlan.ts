import type {
  AnalyticItem,
  CombinedMapData,
  ConnectionsMapParams,
  MapDataResponse,
} from '../api/bff'
import { BASE_MAP_ANALYTIC_ID } from '../analytics/mapAnalyticIds'
import {
  combineMapData,
  type CombineMapDataOptionsBase,
} from '../analytics/mapLayers'

/** Canonical base map analytic id when present in the analytics catalog. */
export function resolveBaseMapAnalyticId(analytics: AnalyticItem[]): string | null {
  return analytics.some((a) => a.id === BASE_MAP_ANALYTIC_ID) ? BASE_MAP_ANALYTIC_ID : null
}

/** User-enabled analytic ids that support map view (selectable only). */
export function enabledMapAnalyticIds(
  enabledAnalyticIds: string[],
  analytics: AnalyticItem[]
): string[] {
  const set = new Set(
    analytics
      .filter((a) => a.supportsMap && a.id !== BASE_MAP_ANALYTIC_ID)
      .map((a) => a.id)
  )
  return enabledAnalyticIds.filter((id) => set.has(id))
}

/** Map data ids to fetch: base map first, then enabled selectable map analytics. */
export function mapIdsToFetch(analytics: AnalyticItem[], enabledMapIds: string[]): string[] {
  const base = resolveBaseMapAnalyticId(analytics)
  const withoutBase = enabledMapIds.filter((id) => id !== base)
  return base ? [base, ...withoutBase] : withoutBase
}

export type CombineMapDataFromQueriesInput = {
  liveConnectionsParams: ConnectionsMapParams | null
  futureTurnOffset: number
}

/** Builds merge options and combines per-analytic map query results in fetch order. */
export function combineMapDataFromAnalyticQueries(
  mapIds: readonly string[],
  mapQueryData: readonly (MapDataResponse | undefined)[],
  input: CombineMapDataFromQueriesInput
): CombinedMapData {
  const mergeOptions: CombineMapDataOptionsBase = {
    liveConnectionsParams: input.liveConnectionsParams,
    stellarCartographyFutureTurnOffset: input.futureTurnOffset,
  }
  return combineMapData(
    mapIds,
    mapQueryData.map((data) => ({ data })),
    mergeOptions
  )
}
