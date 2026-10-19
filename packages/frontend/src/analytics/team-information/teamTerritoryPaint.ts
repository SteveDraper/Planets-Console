import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { isTeamTerritoryKind, isTerritoryKind, territoryPaintKind } from './kinds'

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
 * Drop team-territory fills for unchecked legend rows.
 * Player-territory kinds are not filtered. Hover and the legend outline use
 * the list from before this filter.
 */
export function omitHiddenTeamTerritoryOverlays(
  overlays: readonly MapRegionOverlay[],
  hiddenLeagueTeamIds: readonly number[]
): readonly MapRegionOverlay[] {
  if (hiddenLeagueTeamIds.length === 0) return overlays
  const hidden = new Set(hiddenLeagueTeamIds)
  return overlays.filter((overlay) => {
    if (!isTeamTerritoryKind(overlay.kind)) return true
    const leagueTeamId = overlay.leagueTeamId
    return leagueTeamId == null || !hidden.has(leagueTeamId)
  })
}

/**
 * Paint pipeline: territory kinds stay out of ``paintNonTerritory``
 * (Visibility kind preferences and homeworld selection). The selected kind
 * is inserted back in its original order. Legend visibility is a later filter
 * (``omitHiddenTeamTerritoryOverlays``) so hover can still see hidden teams.
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
