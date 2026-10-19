/**
 * Cell-hover copy for Territory. English lives here.
 * Core emits league team ids and player ids.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { collectRegionOverlayHoverSummaries } from '../../lib/mapRegionOverlayHitTest'
import { isPlayerTerritoryKind, isTeamTerritoryKind } from './kinds'
import { playerTerritoryLegendLabel } from './playerLegend'
import { teamInformationLegendLabel } from './teamLegend'

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

export function formatPlayerTerritoryHoverLine(
  overlay: MapRegionOverlay,
  usernamesByPlayerId: ReadonlyMap<number, string>
): string | null {
  if (!isPlayerTerritoryKind(overlay.kind)) return null
  const playerId = overlay.playerId
  if (playerId == null) return null
  return playerTerritoryLegendLabel(playerId, usernamesByPlayerId)
}

/** One line per player whose painted territory contains the map point. */
export function playerTerritoryHoverLinesAtMapPoint(
  overlays: readonly MapRegionOverlay[],
  mapX: number,
  mapY: number,
  usernamesByPlayerId: ReadonlyMap<number, string>
): string[] {
  const lines = collectRegionOverlayHoverSummaries(overlays, mapX, mapY, (overlay) =>
    formatPlayerTerritoryHoverLine(overlay, usernamesByPlayerId)
  )
  return [...new Set(lines)]
}
