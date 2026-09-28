import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { isTeamTerritoryKind, TEAM_TERRITORY_KIND, TEAM_TERRITORY_OWNED_ONLY_KIND } from './kinds'

/**
 * Keep one team-territory site set. Other kinds pass through.
 * ``ownedPlanetsOnly`` false paints ``team-territory``; true paints
 * ``team-territory-owned-only``.
 */
export function applyTeamTerritorySiteSet(
  overlays: readonly MapRegionOverlay[],
  ownedPlanetsOnly: boolean
): MapRegionOverlay[] {
  const omittedKind = ownedPlanetsOnly ? TEAM_TERRITORY_KIND : TEAM_TERRITORY_OWNED_ONLY_KIND
  return overlays.filter((overlay) => overlay.kind !== omittedKind)
}

/**
 * Paint pipeline: team-territory kinds stay out of ``paintNonTeamTerritory``
 * (Visibility kind preferences and homeworld selection). The selected site set
 * is inserted back in its original order.
 */
export function mapRegionOverlaysForPaint(
  overlays: readonly MapRegionOverlay[],
  ownedPlanetsOnly: boolean,
  paintNonTeamTerritory: (overlays: readonly MapRegionOverlay[]) => readonly MapRegionOverlay[]
): MapRegionOverlay[] {
  const nonTeam = overlays.filter((overlay) => !isTeamTerritoryKind(overlay.kind))
  const paintedNonTeam = paintNonTeamTerritory(nonTeam)
  const paintedById = new Map(paintedNonTeam.map((overlay) => [overlay.id, overlay]))
  const selectedTeam = new Set(
    applyTeamTerritorySiteSet(
      overlays.filter((overlay) => isTeamTerritoryKind(overlay.kind)),
      ownedPlanetsOnly
    )
  )
  const result: MapRegionOverlay[] = []
  for (const overlay of overlays) {
    if (isTeamTerritoryKind(overlay.kind)) {
      if (selectedTeam.has(overlay)) result.push(overlay)
      continue
    }
    const painted = paintedById.get(overlay.id)
    if (painted != null) result.push(painted)
  }
  return result
}
