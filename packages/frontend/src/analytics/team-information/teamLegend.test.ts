import { describe, expect, it } from 'vitest'
import { teamInformationLegendRows } from './teamLegend'
import type { TeamInformationTeam } from './wireSchema'

const teams: TeamInformationTeam[] = [
  { leagueTeamId: 4, fillColor: '#38bdf8', fillPattern: 'solid', playerIds: [2, 7] },
  { leagueTeamId: 9, fillColor: '#f472b6', fillPattern: 'forward', playerIds: [3] },
]

describe('teamInformationLegendRows', () => {
  it('lists team id and member usernames from teams', () => {
    const rows = teamInformationLegendRows(
      teams,
      new Map([
        [2, 'alice'],
        [7, 'bob'],
        [3, 'carol'],
      ])
    )
    expect(rows).toEqual([
      { leagueTeamId: 4, fillColor: '#38bdf8', fillPattern: 'solid', usernames: ['alice', 'bob'] },
      { leagueTeamId: 9, fillColor: '#f472b6', fillPattern: 'forward', usernames: ['carol'] },
    ])
  })

  it('omits player ids that are missing from the roster', () => {
    const rows = teamInformationLegendRows(teams, new Map([[2, 'alice']]))
    expect(rows[0]?.usernames).toEqual(['alice'])
    expect(rows[1]?.usernames).toEqual([])
  })
})
