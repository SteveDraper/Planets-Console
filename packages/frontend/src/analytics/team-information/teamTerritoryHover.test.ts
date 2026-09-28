import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { teamTerritoryHoverLinesAtMapPoint } from './teamTerritoryHover'

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

describe('teamTerritoryHoverLinesAtMapPoint', () => {
  it('names the league team whose territory contains the point', () => {
    expect(
      teamTerritoryHoverLinesAtMapPoint([triangle], 2, 2, new Map([[4, 'Alpha']]))
    ).toEqual(['Alpha'])
  })

  it('uses the numeric id when the directory name is null', () => {
    expect(
      teamTerritoryHoverLinesAtMapPoint([triangle], 2, 2, new Map([[4, null]]))
    ).toEqual(['4'])
  })

  it('returns nothing outside the territory', () => {
    expect(
      teamTerritoryHoverLinesAtMapPoint([triangle], 9, 9, new Map([[4, 'Alpha']]))
    ).toEqual([])
  })

  it('ignores other region kinds even when they carry a league team id', () => {
    const homeworld: MapRegionOverlay = {
      ...triangle,
      kind: 'homeworld-sector',
      id: 'sector',
    }
    expect(
      teamTerritoryHoverLinesAtMapPoint([homeworld], 2, 2, new Map([[4, 'Alpha']]))
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
      teamTerritoryHoverLinesAtMapPoint([triangle, second], 1, 1, new Map([[4, 'Alpha']]))
    ).toEqual(['Alpha'])
  })
})
