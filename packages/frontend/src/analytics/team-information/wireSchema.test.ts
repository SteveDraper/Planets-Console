import { describe, expect, it } from 'vitest'
import { parseTeamInformationPayload } from './wireSchema'

const valid = {
  analyticId: 'team-information',
  sphere: true,
  teams: [{ leagueTeamId: 4, fillColor: '#38bdf8', fillPattern: 'solid', playerIds: [1] }],
  players: [{ playerId: 1 }],
  regionOverlays: [{ kind: 'team-territory' }],
}

describe('parseTeamInformationPayload', () => {
  it('accepts the core map shape', () => {
    expect(parseTeamInformationPayload(valid)).toEqual(valid)
  })

  it('rejects a payload that is missing players', () => {
    const { analyticId, sphere, teams, regionOverlays } = valid
    expect(
      parseTeamInformationPayload({ analyticId, sphere, teams, regionOverlays })
    ).toBeNull()
  })

  it('rejects a payload that is missing teams', () => {
    const { analyticId, sphere, regionOverlays, players } = valid
    expect(parseTeamInformationPayload({ analyticId, sphere, regionOverlays, players })).toBeNull()
  })
})
