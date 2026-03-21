import { describe, it, expect } from 'vitest'
import {
  buildPerspectivesFromGameInfo,
  getLatestTurnFromGameInfo,
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
      { ordinal: 1, name: 'alice' },
      { ordinal: 2, name: 'bob' },
    ])
  })

  it('uses placeholder when username empty', () => {
    const rows = buildPerspectivesFromGameInfo(
      minimalInfo({
        players: [{ username: '   ' }],
      })
    )
    expect(rows[0].name).toBe('Player 1')
  })
})

describe('perspectiveOrdinalForName', () => {
  const p = [
    { ordinal: 1, name: 'Alpha' },
    { ordinal: 2, name: 'Beta' },
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
    { ordinal: 1, name: 'Alpha' },
    { ordinal: 2, name: 'Beta' },
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
