import { describe, expect, it } from 'vitest'
import { stellarCartographySettingsGatesFromGameInfo } from './stellarCartographySettings'
import type { GameInfoResponse } from '../api/bff'

describe('stellarCartographySettingsGatesFromGameInfo', () => {
  it('returns all false when settings are missing', () => {
    expect(stellarCartographySettingsGatesFromGameInfo({ game: { id: 1 } })).toEqual({
      debrisDiskBorders: false,
      starClusters: false,
      nebulae: false,
      ionStorms: false,
      wormholes: false,
      blackHoles: false,
    })
  })

  it('enables gates from positive settings counts', () => {
    const data: GameInfoResponse = {
      game: { id: 673864 },
      settings: {
        ndebrisdiscs: 2,
        stars: 13,
        nebulas: 91,
        maxions: 5,
        maxwormholes: 56,
        blackholes: 1,
      },
    }
    expect(stellarCartographySettingsGatesFromGameInfo(data)).toEqual({
      debrisDiskBorders: true,
      starClusters: true,
      nebulae: true,
      ionStorms: true,
      wormholes: true,
      blackHoles: true,
    })
  })
})
