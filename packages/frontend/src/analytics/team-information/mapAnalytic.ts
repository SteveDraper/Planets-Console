import type { MapDataResponse } from '../../api/bff'
import type {
  MapAnalyticQueryContext,
  MapAnalyticQuerySpec,
  MapAnalyticRegistration,
} from '../mapAnalyticRegistry'
import { TEAM_INFORMATION_ANALYTIC_ID } from '../mapAnalyticIds'
import { fetchTeamInformationMap } from './api'

export function teamInformationMapQueryKey(
  analyticScope: MapAnalyticQueryContext['analyticScope']
) {
  return ['analytic', TEAM_INFORMATION_ANALYTIC_ID, 'map', analyticScope, 'territory-v2'] as const
}

/**
 * Sole owner of the team-information map query key. The owned-planets checkbox
 * is not part of the key, so toggling it does not refetch.
 */
export function teamInformationMapQuerySpec(
  analyticScope: MapAnalyticQueryContext['analyticScope'],
  analyticFetchEnabled: boolean
): MapAnalyticQuerySpec {
  return {
    queryKey: teamInformationMapQueryKey(analyticScope),
    queryFn: async (): Promise<MapDataResponse> => {
      if (analyticScope == null) {
        throw new Error('Team information map query requires analytic scope')
      }
      return fetchTeamInformationMap(analyticScope)
    },
    enabled: analyticFetchEnabled && analyticScope != null,
  }
}

/**
 * Team information: merge both territory partitions into the combined map.
 * The owned-planets checkbox filters kinds at paint time.
 */
export const teamInformationMapAnalytic: MapAnalyticRegistration = {
  buildQuerySpec(context: MapAnalyticQueryContext) {
    return teamInformationMapQuerySpec(context.analyticScope, context.analyticFetchEnabled)
  },
  mergeLayer(data, context) {
    const overlays = data.regionOverlays
    if (overlays == null || overlays.length === 0) return
    context.regionOverlays.push(...overlays)
  },
}
