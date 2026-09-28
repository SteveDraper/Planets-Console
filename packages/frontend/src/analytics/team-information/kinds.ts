/** Team territory site-set kinds. Not Visibility region kinds. */

export const TEAM_TERRITORY_KIND = 'team-territory'

export const TEAM_TERRITORY_OWNED_ONLY_KIND = 'team-territory-owned-only'

export function isTeamTerritoryKind(kind: string): boolean {
  return kind === TEAM_TERRITORY_KIND || kind === TEAM_TERRITORY_OWNED_ONLY_KIND
}
