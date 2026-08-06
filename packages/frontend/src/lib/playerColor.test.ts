import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  PLAYER_COLOR_PRESET,
  colorForPlayerId,
  defaultColorForPlayerId,
  resetPlayerColorOverrideStore,
  setPlayerColorOverrideStore,
} from './playerColor'

describe('playerColor', () => {
  beforeEach(() => {
    resetPlayerColorOverrideStore()
  })

  afterEach(() => {
    resetPlayerColorOverrideStore()
  })

  it('maps playerId % 16 into the preset table', () => {
    expect(defaultColorForPlayerId(0)).toBe(PLAYER_COLOR_PRESET[0])
    expect(defaultColorForPlayerId(1)).toBe(PLAYER_COLOR_PRESET[1])
    expect(defaultColorForPlayerId(15)).toBe(PLAYER_COLOR_PRESET[15])
    expect(defaultColorForPlayerId(16)).toBe(PLAYER_COLOR_PRESET[0])
    expect(defaultColorForPlayerId(-1)).toBe(PLAYER_COLOR_PRESET[15])
  })

  it('uses defaults when the override store is empty', () => {
    expect(colorForPlayerId(8)).toBe(defaultColorForPlayerId(8))
  })

  it('consults the override store before defaults', () => {
    setPlayerColorOverrideStore({
      getOverride: (playerId) => (playerId === 8 ? '#ffffff' : undefined),
    })
    expect(colorForPlayerId(8)).toBe('#ffffff')
    expect(colorForPlayerId(9)).toBe(defaultColorForPlayerId(9))
  })
})
