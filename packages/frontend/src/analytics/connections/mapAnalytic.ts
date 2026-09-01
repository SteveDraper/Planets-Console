import { fetchAnalyticMap } from '../../api/bff'
import type { AnalyticShellScope } from '../../api/bff'
import type {
  MapAnalyticQueryContext,
  MapAnalyticRegistration,
} from '../mapAnalyticRegistry'
import type { ConnectionsMapParams, ConnectionsFlareMode } from './api'
import { CONNECTIONS_ANALYTIC_ID } from '../mapAnalyticIds'
import { appendConnectionsMapLayer } from './mapLayer'
import { useConnectionsMapParamsStore } from './connectionsMapParamsStore'

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

export const connectionsMapAnalytic: MapAnalyticRegistration = {
  buildQuerySpec(context: MapAnalyticQueryContext) {
    const connectionsMapParams = useConnectionsMapParamsStore.getState().connectionsMapParams
    return {
      queryKey: connectionsMapQueryKey(context.analyticScope, connectionsMapParams),
      queryFn: () => fetchAnalyticMap(CONNECTIONS_ANALYTIC_ID, context.analyticScope!),
      enabled: context.analyticFetchEnabled && context.analyticScope != null,
    }
  },
  mergeLayer(data, context, options) {
    if (context.baseMapAnalyticId == null) return
    appendConnectionsMapLayer({
      data,
      baseMapAnalyticId: context.baseMapAnalyticId,
      liveConnectionsParams: options.liveConnectionsParams,
      edges: context.edges,
      waypointsByKey: context.waypointsByKey,
    })
  },
}
