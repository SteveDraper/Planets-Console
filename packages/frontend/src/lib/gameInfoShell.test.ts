import { describe, it, expect } from 'vitest'
import {
  buildPerspectivesFromGameInfo,
  getLatestTurnFromGameInfo,
  getSectorDisplayNameFromGameInfo,
  isGameFinishedFromGameInfo,
  perspectiveOrdinalForName,
  viewpointNameForLogin,
} from './gameInfoShell'
import type { GameInfoResponse } from '../api/bff'

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

describe('buildPerspectivesFromGameInfo', () => {
  it('maps players order to 1-based ordinals and names', () => {
    const rows = buildPerspectivesFromGameInfo(
      minimalInfo({
        players: [{ username: 'alice' }, { username: 'bob' }],
      })
    )
    expect(rows).toEqual([
      { ordinal: 1, name: 'alice', raceName: null },
      { ordinal: 2, name: 'bob', raceName: null },
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
      name: 'alice',
      raceName: 'Override From Turn RST',
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
  const p = [
    { ordinal: 1, name: 'Alpha', raceName: null as string | null },
    { ordinal: 2, name: 'Beta', raceName: null as string | null },
  ]

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
})

describe('viewpointNameForLogin', () => {
  const p = [
    { ordinal: 1, name: 'Alpha', raceName: null as string | null },
    { ordinal: 2, name: 'Beta', raceName: null as string | null },
  ]

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
