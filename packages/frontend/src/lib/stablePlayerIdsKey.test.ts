import { describe, expect, it } from 'vitest'
import { playerIdsFromStableKey, stablePlayerIdsKey } from './stablePlayerIdsKey'

describe('stablePlayerIdsKey', () => {
  it('sorts ids so order changes do not alter the key', () => {
    expect(stablePlayerIdsKey([9, 8])).toBe('8,9')
    expect(stablePlayerIdsKey([8, 9])).toBe('8,9')
  })
})

describe('playerIdsFromStableKey', () => {
  it('round-trips sorted player ids', () => {
    expect(playerIdsFromStableKey('8,9')).toEqual([8, 9])
    expect(playerIdsFromStableKey('')).toEqual([])
  })
})
