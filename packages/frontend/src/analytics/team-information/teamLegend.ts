import type { TeamInformationTeam } from './wireSchema'

export type TeamInformationLegendRow = {
  leagueTeamId: number
  fillColor: string
  fillPattern: TeamInformationTeam['fillPattern']
  usernames: string[]
}

/** Legend rows from the map ``teams`` payload, with roster usernames in player-id order. */
export function teamInformationLegendRows(
  teams: readonly TeamInformationTeam[],
  usernamesByPlayerId: ReadonlyMap<number, string>
): TeamInformationLegendRow[] {
  return teams.map((team) => ({
    leagueTeamId: team.leagueTeamId,
    fillColor: team.fillColor,
    fillPattern: team.fillPattern,
    usernames: team.playerIds.flatMap((playerId) => {
      const username = usernamesByPlayerId.get(playerId)?.trim()
      return username ? [username] : []
    }),
  }))
}
