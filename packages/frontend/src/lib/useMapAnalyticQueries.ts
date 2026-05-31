import { useMemo } from 'react'
import {
  useQueries,
  type FetchStatus,
  type QueryStatus,
  type UseQueryResult,
} from '@tanstack/react-query'
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
  string | number,
  number,
  number,
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

export type MapQueryCombineRevisionEntry = readonly [number, FetchStatus, QueryStatus]

export type MapQueryCombineRevision = readonly MapQueryCombineRevisionEntry[]

type MapQueryRevisionSource = ReadonlyArray<
  Pick<UseQueryResult<unknown, Error>, 'dataUpdatedAt' | 'fetchStatus' | 'status'>
>

/** Serializable revision of map query fetch state used to invalidate combined map data. */
export function mapQueryCombineRevision(mapQueries: MapQueryRevisionSource): MapQueryCombineRevision {
  return mapQueries.map((q) => [q.dataUpdatedAt, q.fetchStatus, q.status] as const)
}

/** Stable string key for `useMemo` deps derived from {@link mapQueryCombineRevision}. */
export function mapQueryCombineRevisionKey(revision: MapQueryCombineRevision): string {
  return revision.map(([dataUpdatedAt, fetchStatus, status]) =>
    `${dataUpdatedAt}:${fetchStatus}:${status}`
  ).join('|')
}

/** Stable query key for the Connections map analytic; uses `idle` placeholders when scope is null. */
export function connectionsMapQueryKey(
  analyticScope: AnalyticShellScope | null,
  connectionsMapParams: ConnectionsMapParams
): ConnectionsMapQueryKey {
  if (analyticScope != null) {
    return [
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
    ]
  }
  return [
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
  ]
}

async function fetchConnectionsMapFromQueryKey(
  queryKey: ConnectionsMapQueryKey
): Promise<MapDataResponse> {
  if (queryKey[3] === 'idle') {
    return {
      analyticId: 'connections',
      nodes: [],
      edges: [],
      routes: [],
    }
  }
  const [, , , gameId, turn, perspective, warpSpeed, gravitonicMovement, flareMode, flareDepth] =
    queryKey
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
        const queryKey = connectionsMapQueryKey(analyticScope, connectionsMapParams)
        return {
          queryKey,
          queryFn: ({ queryKey: qk }: { queryKey: ConnectionsMapQueryKey }) =>
            fetchConnectionsMapFromQueryKey(qk),
          enabled: analyticFetchEnabled,
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
  const liveConnectionsParams =
    mapIds.includes('connections') && analyticFetchEnabled ? connectionsMapParams : null
  const mapIdsKey = mapIds.join('\0')
  const includesStellarCartography = mapIds.includes('stellar-cartography')
  const mapQueryRevisionKey = mapQueryCombineRevisionKey(mapQueryCombineRevision(mapQueries))

  const combined = useMemo(
    () =>
      combineMapData(
        mapIds,
        mapQueries.map((q) => ({ data: q.data })),
        includesStellarCartography
          ? {
              liveConnectionsParams,
              futureTurnOffset,
              stellarCartography,
            }
          : { liveConnectionsParams, futureTurnOffset }
      ),
    [
      mapIdsKey,
      mapQueryRevisionKey,
      liveConnectionsParams,
      analyticFetchEnabled,
      includesStellarCartography,
      connectionsMapParams.flareMode,
      connectionsMapParams.warpSpeed,
      connectionsMapParams.gravitonicMovement,
      connectionsMapParams.flareDepth,
      futureTurnOffset,
      stellarCartography.layerVisibility,
      stellarCartography.settingsGates,
      stellarCartography.wormholeDisplayMode,
      stellarCartography.starClusterDisplayMode,
      stellarCartography.neutronClusterDisplayMode,
    ]
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
