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
  return ['analytic', TEAM_INFORMATION_ANALYTIC_ID, 'map', analyticScope, 'territory-v3'] as const
}

/**
 * Sole owner of the team-information map query key. By team and owned-planets
 * are not part of the key, so toggling them does not refetch.
 */
export function teamInformationMapQuerySpec(
  analyticScope: MapAnalyticQueryContext['analyticScope'],
  analyticFetchEnabled: boolean
): MapAnalyticQuerySpec {
  return {
    queryKey: teamInformationMapQueryKey(analyticScope),
    queryFn: async (): Promise<MapDataResponse> => {
      if (analyticScope == null) {
        throw new Error('Territory map query requires analytic scope')
      }
      return fetchTeamInformationMap(analyticScope)
    },
    enabled: analyticFetchEnabled && analyticScope != null,
  }
}

/**
 * Territory: merge every site-set and partition into the combined map.
 * The checkboxes filter kinds at paint time.
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
