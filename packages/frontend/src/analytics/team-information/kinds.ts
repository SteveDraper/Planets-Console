/** Territory site-set kinds. Not Visibility region kinds. */

export const TEAM_TERRITORY_KIND = 'team-territory'

export const TEAM_TERRITORY_OWNED_ONLY_KIND = 'team-territory-owned-only'

export const PLAYER_TERRITORY_KIND = 'player-territory'

export const PLAYER_TERRITORY_OWNED_ONLY_KIND = 'player-territory-owned-only'

export function isTeamTerritoryKind(kind: string): boolean {
  return kind === TEAM_TERRITORY_KIND || kind === TEAM_TERRITORY_OWNED_ONLY_KIND
}

export function isPlayerTerritoryKind(kind: string): boolean {
  return kind === PLAYER_TERRITORY_KIND || kind === PLAYER_TERRITORY_OWNED_ONLY_KIND
}

/** Either partition. These kinds stay out of Visibility kind preferences. */
export function isTerritoryKind(kind: string): boolean {
  return isTeamTerritoryKind(kind) || isPlayerTerritoryKind(kind)
}

/** The one overlay kind painted for the checkbox pair. */
export function territoryPaintKind(byTeam: boolean, ownedPlanetsOnly: boolean): string {
  if (byTeam) {
    return ownedPlanetsOnly ? TEAM_TERRITORY_OWNED_ONLY_KIND : TEAM_TERRITORY_KIND
  }
  return ownedPlanetsOnly ? PLAYER_TERRITORY_OWNED_ONLY_KIND : PLAYER_TERRITORY_KIND
}
