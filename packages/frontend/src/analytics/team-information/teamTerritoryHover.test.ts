import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { territoryHoverLinesAtMapPoint } from './teamTerritoryHover'

function territory(leagueTeamId: number, vertices: { x: number; y: number }[]): MapRegionOverlay {
  return {
    kind: 'team-territory',
    id: `team-territory:${leagueTeamId}:0`,
    fillColor: '#38bdf8',
    fillOpacity: 0.35,
    leagueTeamId,
    geometry: {
      type: 'boundary',
      vertices,
      edges: vertices.map(() => ({ type: 'line' as const })),
    },
  }
}

const triangle = territory(4, [
  { x: 0, y: 0 },
  { x: 10, y: 0 },
  { x: 0, y: 10 },
])

const noNames = new Map<number, string | null>()
const noUsernames = new Map<number, string>()

describe('territoryHoverLinesAtMapPoint', () => {
  it('names the league team whose territory contains the point', () => {
    expect(
      territoryHoverLinesAtMapPoint(
        [triangle],
        2,
        2,
        'team',
        new Map([[4, 'Alpha']]),
        noUsernames
      )
    ).toEqual(['Alpha'])
  })

  it('uses the numeric id when the directory name is null', () => {
    expect(
      territoryHoverLinesAtMapPoint([triangle], 2, 2, 'team', new Map([[4, null]]), noUsernames)
    ).toEqual(['4'])
  })

  it('returns nothing outside the territory', () => {
    expect(
      territoryHoverLinesAtMapPoint(
        [triangle],
        9,
        9,
        'team',
        new Map([[4, 'Alpha']]),
        noUsernames
      )
    ).toEqual([])
  })

  it('ignores other region kinds even when they carry a league team id', () => {
    const homeworld: MapRegionOverlay = {
      ...triangle,
      kind: 'homeworld-sector',
      id: 'sector',
    }
    expect(
      territoryHoverLinesAtMapPoint(
        [homeworld],
        2,
        2,
        'team',
        new Map([[4, 'Alpha']]),
        noUsernames
      )
    ).toEqual([])
  })

  it('lists one line when two components of the same team contain the point', () => {
    const second = territory(4, [
      { x: 0, y: 0 },
      { x: 8, y: 0 },
      { x: 0, y: 8 },
    ])
    second.id = 'team-territory:4:1'
    expect(
      territoryHoverLinesAtMapPoint(
        [triangle, second],
        1,
        1,
        'team',
        new Map([[4, 'Alpha']]),
        noUsernames
      )
    ).toEqual(['Alpha'])
  })

  const playerRegion: MapRegionOverlay = {
    kind: 'player-territory',
    id: 'player-territory:1:0',
    fillColor: '#000000',
    fillOpacity: 0.35,
    fillPattern: 'solid',
    playerId: 1,
    geometry: triangle.geometry,
  }

  it('names the player whose territory contains the point', () => {
    expect(
      territoryHoverLinesAtMapPoint(
        [playerRegion],
        2,
        2,
        'player',
        noNames,
        new Map([[1, 'alice']])
      )
    ).toEqual(['alice'])
  })

  it('uses the numeric id when the username is missing', () => {
    expect(
      territoryHoverLinesAtMapPoint([playerRegion], 2, 2, 'player', noNames, noUsernames)
    ).toEqual(['1'])
  })

  it('ignores league-team territory while the player partition is active', () => {
    expect(
      territoryHoverLinesAtMapPoint([triangle], 2, 2, 'player', noNames, new Map([[1, 'alice']]))
    ).toEqual([])
  })

  it('labels only the active partition when both unions contain the point', () => {
    const names = new Map<number, string | null>([[4, 'Alpha']])
    const usernames = new Map([[1, 'alice']])
    expect(
      territoryHoverLinesAtMapPoint([triangle, playerRegion], 2, 2, 'team', names, usernames)
    ).toEqual(['Alpha'])
    expect(
      territoryHoverLinesAtMapPoint([triangle, playerRegion], 2, 2, 'player', names, usernames)
    ).toEqual(['alice'])
  })
})
