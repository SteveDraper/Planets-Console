import { describe, it, expect } from 'vitest'
import {
  buildPerspectivesFromGameInfo,
  perspectiveDisplayName,
  getLatestTurnFromGameInfo,
  getSectorDisplayNameFromGameInfo,
  isGameFinishedFromGameInfo,
  isLoginAmongGamePlayers,
  perspectiveOrdinalForName,
  perspectiveNameForOrdinal,
  playerIdForViewpointName,
  shouldUsePseudoViewpointForLogin,
  selectableTurnMaxForShell,
  SPECTATOR_VIEWPOINT_NAME,
  viewpointNameForStoredPerspective,
  viewpointNameForLogin,
} from './gameInfoShell'
import type { GameInfoResponse } from '../api/bff'
import { perspectiveRow } from './perspectiveRowTestFixtures'

const minimalInfo = (overrides: Partial<GameInfoResponse> = {}): GameInfoResponse => ({
  game: { id: 1 },
  ...overrides,
})

describe('isGameFinishedFromGameInfo', () => {
  it('is false when game missing or status unknown', () => {
    expect(isGameFinishedFromGameInfo(minimalInfo())).toBe(false)
    expect(isGameFinishedFromGameInfo(minimalInfo({ game: { id: 1, status: 1 } }))).toBe(false)
  })

  it('is true for numeric status 3 (planets.nu finished)', () => {
    expect(isGameFinishedFromGameInfo(minimalInfo({ game: { id: 1, status: 3 } }))).toBe(true)
  })

  it('is true for string status "3"', () => {
    expect(isGameFinishedFromGameInfo(minimalInfo({ game: { id: 1, status: '3' } }))).toBe(true)
  })

  it('is true when statusname is Finished', () => {
    expect(
      isGameFinishedFromGameInfo(minimalInfo({ game: { id: 1, statusname: 'Finished' } }))
    ).toBe(true)
    expect(
      isGameFinishedFromGameInfo(minimalInfo({ game: { id: 1, statusname: 'finished' } }))
    ).toBe(true)
  })
})

describe('getLatestTurnFromGameInfo', () => {
  it('prefers game.turn', () => {
    expect(
      getLatestTurnFromGameInfo(minimalInfo({ game: { id: 1, turn: 42 }, settings: { turn: 1 } }))
    ).toBe(42)
  })

  it('falls back to settings.turn', () => {
    expect(getLatestTurnFromGameInfo(minimalInfo({ settings: { turn: 7 } }))).toBe(7)
  })

  it('returns null when missing', () => {
    expect(getLatestTurnFromGameInfo(minimalInfo())).toBeNull()
  })
})

describe('perspectiveDisplayName', () => {
  const eliminated = perspectiveRow(1, 'dead', {
    playerId: 1,
    raceName: 'Feds',
    eliminationTurn: 49,
  })

  it('uses turn username when viewing before elimination', () => {
    expect(
      perspectiveDisplayName(eliminated, 8, new Map([[1, 'dougp314']]))
    ).toBe('dougp314')
  })

  it('falls back to game-info name at or after elimination', () => {
    expect(
      perspectiveDisplayName(eliminated, 49, new Map([[1, 'dougp314']]))
    ).toBe('dead')
  })
})

describe('buildPerspectivesFromGameInfo', () => {
  it('maps players order to 1-based ordinals and names', () => {
    const rows = buildPerspectivesFromGameInfo(
      minimalInfo({
        players: [{ username: 'alice' }, { username: 'bob' }],
      })
    )
    expect(rows).toEqual([
      { ordinal: 1, name: 'alice', playerId: 1, raceName: null, eliminationTurn: null },
      { ordinal: 2, name: 'bob', playerId: 2, raceName: null, eliminationTurn: null },
    ])
  })

  it('uses placeholder when username empty', () => {
    const rows = buildPerspectivesFromGameInfo(
      minimalInfo({
        players: [{ username: '   ' }],
      })
    )
    expect(rows[0].name).toBe('Player 1')
    expect(rows[0].raceName).toBeNull()
  })

  it('prefers wire races[] over the static catalog when both exist', () => {
    const rows = buildPerspectivesFromGameInfo(
      minimalInfo({
        players: [{ username: 'alice', raceid: 2 }],
        races: [{ id: 2, name: 'Override From Turn RST' }],
      })
    )
    expect(rows[0]).toEqual({
      ordinal: 1,
      playerId: 1,
      name: 'alice',
      raceName: 'Override From Turn RST',
      eliminationTurn: null,
    })
  })

  it('uses the static catalog when races[] is absent (planets.nu loadinfo)', () => {
    const rows = buildPerspectivesFromGameInfo(
      minimalInfo({
        players: [{ username: 'bob', raceid: 8 }],
      })
    )
    expect(rows[0].raceName).toBe('The Evil Empire')
  })

  it('uses host player id from game info when present', () => {
    const rows = buildPerspectivesFromGameInfo(
      minimalInfo({
        players: [{ username: 'alice', id: 42 }, { username: 'bob' }],
      })
    )
    expect(rows[0].playerId).toBe(42)
    expect(rows[1].playerId).toBe(2)
  })

  it('records elimination turn from wire status 3', () => {
    const rows = buildPerspectivesFromGameInfo(
      minimalInfo({
        players: [{ username: 'dead', status: 3, statusturn: 49, id: 1 }],
      })
    )
    expect(rows[0]?.eliminationTurn).toBe(49)
    expect(rows[0]?.name).toBe('dead')
  })
})

describe('getSectorDisplayNameFromGameInfo', () => {
  it('prefers game.name over settings.name', () => {
    expect(
      getSectorDisplayNameFromGameInfo(
        minimalInfo({
          game: { id: 1, name: 'Sector A' },
          settings: { name: 'Sector B' },
        })
      )
    ).toBe('Sector A')
  })

  it('falls back to settings.name', () => {
    expect(
      getSectorDisplayNameFromGameInfo(minimalInfo({ settings: { name: 'Only Here' } }))
    ).toBe('Only Here')
  })

  it('returns null when missing', () => {
    expect(getSectorDisplayNameFromGameInfo(minimalInfo())).toBeNull()
  })
})

describe('perspectiveOrdinalForName', () => {
  const p = [perspectiveRow(1, 'Alpha'), perspectiveRow(2, 'Beta')]

  it('returns null for empty name', () => {
    expect(perspectiveOrdinalForName(p, null)).toBeNull()
    expect(perspectiveOrdinalForName(p, '')).toBeNull()
    expect(perspectiveOrdinalForName(p, '   ')).toBeNull()
  })

  it('returns ordinal for exact name match', () => {
    expect(perspectiveOrdinalForName(p, 'Beta')).toBe(2)
  })

  it('returns null when name not in list', () => {
    expect(perspectiveOrdinalForName(p, 'Gamma')).toBeNull()
  })

  it('returns 0 for spectator pseudo-viewpoint', () => {
    expect(perspectiveOrdinalForName(p, SPECTATOR_VIEWPOINT_NAME)).toBe(0)
  })
})

describe('viewpointNameForStoredPerspective', () => {
  const p = [perspectiveRow(1, 'Alpha'), perspectiveRow(2, 'Beta')]

  it('returns spectator label for pseudo slot 0', () => {
    expect(viewpointNameForStoredPerspective(0, p)).toBe(SPECTATOR_VIEWPOINT_NAME)
  })

  it('returns player name for 1-based slots', () => {
    expect(viewpointNameForStoredPerspective(2, p)).toBe('Beta')
  })
})

describe('isLoginAmongGamePlayers', () => {
  const p = [perspectiveRow(1, 'Alpha'), perspectiveRow(2, 'Beta')]

  it('is false when login empty', () => {
    expect(isLoginAmongGamePlayers(p, null)).toBe(false)
    expect(isLoginAmongGamePlayers(p, '   ')).toBe(false)
  })

  it('matches login case-insensitively', () => {
    expect(isLoginAmongGamePlayers(p, 'beta')).toBe(true)
  })

  it('is false when login not in list', () => {
    expect(isLoginAmongGamePlayers(p, 'nobody')).toBe(false)
  })
})

describe('shouldUsePseudoViewpointForLogin', () => {
  const p = [perspectiveRow(1, 'Alpha'), perspectiveRow(2, 'Beta')]

  it('is true for in-progress game when login is not a player', () => {
    expect(shouldUsePseudoViewpointForLogin(p, 'nobody', false)).toBe(true)
  })

  it('is false when login matches a player', () => {
    expect(shouldUsePseudoViewpointForLogin(p, 'Beta', false)).toBe(false)
  })

  it('is false when game is finished', () => {
    expect(shouldUsePseudoViewpointForLogin(p, 'nobody', true)).toBe(false)
  })

  it('is false when login is empty', () => {
    expect(shouldUsePseudoViewpointForLogin(p, '', false)).toBe(false)
  })
})

describe('selectableTurnMaxForShell', () => {
  it('uses full latest turn when known', () => {
    expect(selectableTurnMaxForShell(50)).toBe(50)
  })

  it('returns null when latest turn is missing', () => {
    expect(selectableTurnMaxForShell(null)).toBeNull()
  })
})

describe('viewpointNameForLogin', () => {
  const p = [perspectiveRow(1, 'Alpha'), perspectiveRow(2, 'Beta')]

  it('returns first when no login', () => {
    expect(viewpointNameForLogin(p, null)).toBe('Alpha')
  })

  it('matches login case-insensitively', () => {
    expect(viewpointNameForLogin(p, 'BETA')).toBe('Beta')
  })

  it('returns first when login not in list', () => {
    expect(viewpointNameForLogin(p, 'nobody')).toBe('Alpha')
  })
})

describe('perspectiveNameForOrdinal', () => {
  const p = [perspectiveRow(1, 'Alpha'), perspectiveRow(2, 'Beta')]

  it('returns name for known ordinal', () => {
    expect(perspectiveNameForOrdinal(p, 2)).toBe('Beta')
  })

  it('returns null for unknown ordinal', () => {
    expect(perspectiveNameForOrdinal(p, 99)).toBeNull()
  })
})

describe('playerIdForViewpointName', () => {
  const p = [
    perspectiveRow(1, 'Alpha', { playerId: 8 }),
    perspectiveRow(2, 'Beta', { playerId: 9 }),
  ]

  it('returns null for empty name', () => {
    expect(playerIdForViewpointName(p, null)).toBeNull()
    expect(playerIdForViewpointName(p, '')).toBeNull()
    expect(playerIdForViewpointName(p, '   ')).toBeNull()
  })

  it('returns host player id for exact name match', () => {
    expect(playerIdForViewpointName(p, 'Beta')).toBe(9)
  })

  it('returns null when name not in list', () => {
    expect(playerIdForViewpointName(p, 'Gamma')).toBeNull()
  })
})
