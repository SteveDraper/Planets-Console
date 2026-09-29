import { describe, expect, it } from 'vitest'
import {
  teamInformationLegendHoverTitle,
  teamInformationLegendRows,
  teamInformationLegendText,
} from './teamLegend'
import type { TeamInformationTeam } from './wireSchema'

const teams: TeamInformationTeam[] = [
  { leagueTeamId: 4, fillColor: '#38bdf8', fillPattern: 'solid', playerIds: [2, 7] },
  { leagueTeamId: 9, fillColor: '#f472b6', fillPattern: 'forward', playerIds: [3] },
]

const roster = new Map([
  [2, 'alice'],
  [7, 'bob'],
  [3, 'carol'],
])

describe('teamInformationLegendRows', () => {
  it('uses the directory name as legend text and keeps member usernames', () => {
    const rows = teamInformationLegendRows(
      teams,
      roster,
      new Map([
        [4, 'Alpha'],
        [9, 'Beta'],
      ])
    )
    expect(rows).toEqual([
      {
        leagueTeamId: 4,
        fillColor: '#38bdf8',
        fillPattern: 'solid',
        name: 'Alpha',
        usernames: ['alice', 'bob'],
      },
      {
        leagueTeamId: 9,
        fillColor: '#f472b6',
        fillPattern: 'forward',
        name: 'Beta',
        usernames: ['carol'],
      },
    ])
    expect(rows.map((row) => teamInformationLegendText(row))).toEqual(['Alpha', 'Beta'])
  })

  it('uses the numeric id when the directory name is null or blank', () => {
    const rows = teamInformationLegendRows(
      teams,
      roster,
      new Map<number, string | null>([
        [4, null],
        [9, '  '],
      ])
    )
    expect(rows[0]?.name).toBeNull()
    expect(rows[1]?.name).toBeNull()
    expect(teamInformationLegendText(rows[0]!)).toBe('4')
    expect(teamInformationLegendText(rows[1]!)).toBe('9')
    expect(rows[0]?.usernames).toEqual(['alice', 'bob'])
    expect(teamInformationLegendHoverTitle(rows[0]!.usernames)).toBe('alice, bob')
    expect(teamInformationLegendHoverTitle([])).toBeUndefined()
  })

  it('omits player ids that are missing from the roster', () => {
    const rows = teamInformationLegendRows(teams, new Map([[2, 'alice']]), new Map())
    expect(rows[0]?.usernames).toEqual(['alice'])
    expect(rows[1]?.usernames).toEqual([])
  })
})
