/**
 * Cell-hover copy for team territory. English lives here; Core emits league team ids.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { collectRegionOverlayHoverSummaries } from '../../lib/mapRegionOverlayHitTest'
import { teamInformationLegendLabel } from './teamLegend'
import { isTeamTerritoryKind } from './kinds'

export function formatTeamTerritoryHoverLine(
  overlay: MapRegionOverlay,
  namesByLeagueTeamId: ReadonlyMap<number, string | null>
): string | null {
  if (!isTeamTerritoryKind(overlay.kind)) return null
  const leagueTeamId = overlay.leagueTeamId
  if (leagueTeamId == null) return null
  return teamInformationLegendLabel(leagueTeamId, namesByLeagueTeamId)
}

/** One line per league team whose painted territory contains the map point. */
export function teamTerritoryHoverLinesAtMapPoint(
  overlays: readonly MapRegionOverlay[],
  mapX: number,
  mapY: number,
  namesByLeagueTeamId: ReadonlyMap<number, string | null>
): string[] {
  const lines = collectRegionOverlayHoverSummaries(overlays, mapX, mapY, (overlay) =>
    formatTeamTerritoryHoverLine(overlay, namesByLeagueTeamId)
  )
  return [...new Set(lines)]
}
