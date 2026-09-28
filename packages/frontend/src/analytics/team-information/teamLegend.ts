import type { TeamInformationTeam } from './wireSchema'

export type TeamInformationLegendRow = {
  leagueTeamId: number
  fillColor: string
  fillPattern: TeamInformationTeam['fillPattern']
  /** Resolved directory name. Null when the directory has no usable name. */
  name: string | null
  usernames: string[]
}

function directoryName(
  namesByLeagueTeamId: ReadonlyMap<number, string | null>,
  leagueTeamId: number
): string | null {
  const raw = namesByLeagueTeamId.get(leagueTeamId)
  if (raw == null) return null
  const trimmed = raw.trim()
  return trimmed.length > 0 ? trimmed : null
}

/** Visible legend text: directory name, or the numeric id when that name is unresolved. */
export function teamInformationLegendText(
  row: Pick<TeamInformationLegendRow, 'leagueTeamId' | 'name'>
): string {
  return row.name ?? String(row.leagueTeamId)
}

/** Same label as the legend row, resolved from the league team directory. */
export function teamInformationLegendLabel(
  leagueTeamId: number,
  namesByLeagueTeamId: ReadonlyMap<number, string | null>
): string {
  return teamInformationLegendText({
    leagueTeamId,
    name: directoryName(namesByLeagueTeamId, leagueTeamId),
  })
}

/** Legend hover text: member usernames. Undefined when the roster resolved none. */
export function teamInformationLegendHoverTitle(
  usernames: readonly string[]
): string | undefined {
  if (usernames.length === 0) return undefined
  return usernames.join(', ')
}

/**
 * Legend rows from the map ``teams`` payload.
 * ``name`` comes from the league team directory. Usernames stay on the row for a later hover.
 */
export function teamInformationLegendRows(
  teams: readonly TeamInformationTeam[],
  usernamesByPlayerId: ReadonlyMap<number, string>,
  namesByLeagueTeamId: ReadonlyMap<number, string | null>
): TeamInformationLegendRow[] {
  return teams.map((team) => ({
    leagueTeamId: team.leagueTeamId,
    fillColor: team.fillColor,
    fillPattern: team.fillPattern,
    name: directoryName(namesByLeagueTeamId, team.leagueTeamId),
    usernames: team.playerIds.flatMap((playerId) => {
      const username = usernamesByPlayerId.get(playerId)?.trim()
      return username ? [username] : []
    }),
  }))
}
