import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  isPlayerTerritoryKind,
  isTeamTerritoryKind,
  isTerritoryKind,
  territoryOwnerId,
  territoryPaintKind,
  territoryPartition,
  type HoveredTerritory,
} from './kinds'

/**
 * Keep one territory kind. Other kinds pass through.
 * ``byTeam`` chooses league-team vs player union. ``ownedPlanetsOnly`` chooses
 * the site set. Exactly one of the four territory kinds remains.
 */
export function applyTerritoryKindFilter(
  overlays: readonly MapRegionOverlay[],
  byTeam: boolean,
  ownedPlanetsOnly: boolean
): MapRegionOverlay[] {
  const kept = territoryPaintKind(byTeam, ownedPlanetsOnly)
  return overlays.filter((overlay) => !isTerritoryKind(overlay.kind) || overlay.kind === kept)
}

/**
 * Overlays to outline for the legend hover.
 * A hover applies only while its partition is the active one.
 * Callers pass overlays from before ``omitHiddenTerritoryOverlays``
 * so a hidden league team or player still outlines.
 */
export function territoryOverlaysForHighlight(
  overlays: readonly MapRegionOverlay[],
  hovered: HoveredTerritory | null,
  byTeam: boolean
): MapRegionOverlay[] {
  if (hovered == null || hovered.partition !== territoryPartition(byTeam)) return []
  return overlays.filter(
    (overlay) => territoryOwnerId(overlay, hovered.partition) === hovered.id
  )
}

/**
 * Drop territory fills for unchecked legend rows.
 * A hidden league team drops only team-territory kinds.
 * A hidden player drops both player site sets and leaves team-territory overlays.
 * Other kinds pass through. Hover and the legend outline use the list from
 * before this filter.
 */
export function omitHiddenTerritoryOverlays(
  overlays: readonly MapRegionOverlay[],
  hiddenLeagueTeamIds: readonly number[],
  hiddenPlayerIds: readonly number[]
): readonly MapRegionOverlay[] {
  if (hiddenLeagueTeamIds.length === 0 && hiddenPlayerIds.length === 0) return overlays
  const hiddenTeams = new Set(hiddenLeagueTeamIds)
  const hiddenPlayers = new Set(hiddenPlayerIds)
  return overlays.filter((overlay) => {
    if (isTeamTerritoryKind(overlay.kind)) {
      const leagueTeamId = overlay.leagueTeamId
      return leagueTeamId == null || !hiddenTeams.has(leagueTeamId)
    }
    if (isPlayerTerritoryKind(overlay.kind)) {
      const playerId = overlay.playerId
      return playerId == null || !hiddenPlayers.has(playerId)
    }
    return true
  })
}

/**
 * Paint pipeline: territory kinds stay out of ``paintNonTerritory``
 * (Visibility kind preferences and homeworld selection). The selected kind
 * is inserted back in its original order. Legend visibility is a later filter
 * (``omitHiddenTerritoryOverlays``) so hover can still see hidden owners.
 */
export function mapRegionOverlaysForPaint(
  overlays: readonly MapRegionOverlay[],
  byTeam: boolean,
  ownedPlanetsOnly: boolean,
  paintNonTerritory: (overlays: readonly MapRegionOverlay[]) => readonly MapRegionOverlay[]
): MapRegionOverlay[] {
  const nonTerritory = overlays.filter((overlay) => !isTerritoryKind(overlay.kind))
  const paintedNonTerritory = paintNonTerritory(nonTerritory)
  const paintedById = new Map(paintedNonTerritory.map((overlay) => [overlay.id, overlay]))
  const selectedTerritory = new Set(
    applyTerritoryKindFilter(
      overlays.filter((overlay) => isTerritoryKind(overlay.kind)),
      byTeam,
      ownedPlanetsOnly
    )
  )
  const result: MapRegionOverlay[] = []
  for (const overlay of overlays) {
    if (isTerritoryKind(overlay.kind)) {
      if (selectedTerritory.has(overlay)) result.push(overlay)
      continue
    }
    const painted = paintedById.get(overlay.id)
    if (painted != null) result.push(painted)
  }
  return result
}
