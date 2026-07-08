import { describe, it, expect } from 'vitest'
import { turnUsernamesByPlayerIdFromPayload } from './turnPlayerUsernames'

describe('turnUsernamesByPlayerIdFromPayload', () => {
  it('maps perspective player and roster entries by id', () => {
    const map = turnUsernamesByPlayerIdFromPayload({
      player: { id: 1, username: 'alice' },
      players: [
        { id: 2, username: 'bob' },
        { id: 1, username: 'ignored-dup' },
      ],
    })
    expect(map.get(1)).toBe('alice')
    expect(map.get(2)).toBe('bob')
  })

  it('returns empty map for non-objects', () => {
    expect(turnUsernamesByPlayerIdFromPayload(null).size).toBe(0)
  })
})
