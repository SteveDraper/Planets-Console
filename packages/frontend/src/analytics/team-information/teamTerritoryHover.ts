/**
 * Cell-hover copy for Territory. English lives here.
 * Core emits league team ids and player ids.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { collectRegionOverlayHoverSummaries } from '../../lib/mapRegionOverlayHitTest'
import {
  territoryOwnerId,
  type TerritoryPartition,
} from './kinds'
import { playerTerritoryLegendLabel } from './playerLegend'
import { teamInformationLegendLabel } from './teamLegend'

function territoryHoverLabel(
  ownerId: number,
  partition: TerritoryPartition,
  namesByLeagueTeamId: ReadonlyMap<number, string | null>,
  usernamesByPlayerId: ReadonlyMap<number, string>
): string {
  switch (partition) {
    case 'team':
      return teamInformationLegendLabel(ownerId, namesByLeagueTeamId)
    case 'player':
      return playerTerritoryLegendLabel(ownerId, usernamesByPlayerId)
  }
}

/** One line per owner whose painted territory contains the map point. */
export function territoryHoverLinesAtMapPoint(
  overlays: readonly MapRegionOverlay[],
  mapX: number,
  mapY: number,
  partition: TerritoryPartition,
  namesByLeagueTeamId: ReadonlyMap<number, string | null>,
  usernamesByPlayerId: ReadonlyMap<number, string>
): string[] {
  const lines = collectRegionOverlayHoverSummaries(overlays, mapX, mapY, (overlay) => {
    const ownerId = territoryOwnerId(overlay, partition)
    if (ownerId == null) return null
    return territoryHoverLabel(ownerId, partition, namesByLeagueTeamId, usernamesByPlayerId)
  })
  return [...new Set(lines)]
}
