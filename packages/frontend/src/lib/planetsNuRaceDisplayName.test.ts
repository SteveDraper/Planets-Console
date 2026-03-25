import { describe, it, expect } from 'vitest'
import type { GameInfoResponse } from '../api/bff'
import {
  planetsNuRaceDisplayNameFromCatalog,
  resolveRaceDisplayNameFromGameInfo,
} from './planetsNuRaceDisplayName'

describe('planetsNuRaceDisplayNameFromCatalog', () => {
  it('returns known HOST ids', () => {
    expect(planetsNuRaceDisplayNameFromCatalog(1)).toBe('The Solar Federation')
    expect(planetsNuRaceDisplayNameFromCatalog(11)).toBe('The Colonies of Man')
  })

  it('returns null for unknown ids', () => {
    expect(planetsNuRaceDisplayNameFromCatalog(99)).toBeNull()
  })
})

describe('resolveRaceDisplayNameFromGameInfo', () => {
  const minimal = (overrides: Partial<GameInfoResponse> = {}): GameInfoResponse => ({
    game: { id: 1 },
    ...overrides,
  })

  it('prefers wire races when present', () => {
    expect(
      resolveRaceDisplayNameFromGameInfo(
        2,
        minimal({
          races: [{ id: 2, name: 'Wire only' }],
        })
      )
    ).toBe('Wire only')
  })

  it('falls back to the catalog', () => {
    expect(resolveRaceDisplayNameFromGameInfo(3, minimal())).toBe('The Bird Men')
  })
})
