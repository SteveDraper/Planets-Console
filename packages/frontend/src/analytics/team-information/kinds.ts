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

/** Active territory union. League team ids and player ids are different entities. */
export type TerritoryPartition = 'player' | 'team'

export type HoveredTerritory = {
  partition: TerritoryPartition
  id: number
}

export function territoryPartition(byTeam: boolean): TerritoryPartition {
  return byTeam ? 'team' : 'player'
}

/** Owner id for this partition. Null when the overlay is a different union. */
export function territoryOwnerId(
  overlay: { kind: string; leagueTeamId?: number; playerId?: number },
  partition: TerritoryPartition
): number | null {
  switch (partition) {
    case 'team':
      if (!isTeamTerritoryKind(overlay.kind) || overlay.leagueTeamId == null) return null
      return overlay.leagueTeamId
    case 'player':
      if (!isPlayerTerritoryKind(overlay.kind) || overlay.playerId == null) return null
      return overlay.playerId
  }
}

/** The one overlay kind painted for the checkbox pair. */
export function territoryPaintKind(byTeam: boolean, ownedPlanetsOnly: boolean): string {
  if (territoryPartition(byTeam) === 'team') {
    return ownedPlanetsOnly ? TEAM_TERRITORY_OWNED_ONLY_KIND : TEAM_TERRITORY_KIND
  }
  return ownedPlanetsOnly ? PLAYER_TERRITORY_OWNED_ONLY_KIND : PLAYER_TERRITORY_KIND
}
