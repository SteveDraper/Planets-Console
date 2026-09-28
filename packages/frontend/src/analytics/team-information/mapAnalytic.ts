import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import type { MapAnalyticRegistration } from '../mapAnalyticRegistry'

/** All-planets team territory kind. */
export const TEAM_TERRITORY_KIND = 'team-territory'

/** Region overlays painted for Team information: the all-planets partition. */
export function teamInformationRegionOverlays(
  overlays: readonly MapRegionOverlay[] | undefined,
): MapRegionOverlay[] {
  if (overlays == null || overlays.length === 0) return []
  return overlays.filter((overlay) => overlay.kind === TEAM_TERRITORY_KIND)
}

export const teamInformationMapAnalytic: MapAnalyticRegistration = {
  mergeLayer(data, context) {
    context.regionOverlays.push(...teamInformationRegionOverlays(data.regionOverlays))
  },
}
