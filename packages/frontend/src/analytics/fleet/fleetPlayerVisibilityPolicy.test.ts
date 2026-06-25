import { describe, expect, it } from 'vitest'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import {
  defaultFleetPlayerVisible,
  orderFleetSidebarPlayers,
  resolveFleetPlayerVisible,
  visibleFleetPlayerIds,
} from './fleetPlayerVisibilityPolicy'

const players: PerspectiveRow[] = [
  { ordinal: 1, playerId: 8, name: 'Alice', raceName: null },
  { ordinal: 2, playerId: 9, name: 'Bob', raceName: null },
  { ordinal: 3, playerId: 10, name: 'Carol', raceName: null },
]

describe('fleetPlayerVisibilityPolicy', () => {
  it('defaults to all players visible', () => {
    expect(defaultFleetPlayerVisible(8, 8)).toBe(true)
    expect(defaultFleetPlayerVisible(9, 8)).toBe(true)
    expect(defaultFleetPlayerVisible(8, null)).toBe(true)
  })

  it('uses persisted overrides when present', () => {
    expect(resolveFleetPlayerVisible(9, 8, { '9': false })).toBe(false)
    expect(resolveFleetPlayerVisible(8, 8, { '8': false })).toBe(false)
    expect(resolveFleetPlayerVisible(10, 8, {})).toBe(true)
  })

  it('orders viewpoint player first in the sidebar', () => {
    expect(orderFleetSidebarPlayers(players, 9).map((player) => player.name)).toEqual([
      'Bob',
      'Alice',
      'Carol',
    ])
  })

  it('returns visible fleet player ids from defaults and overrides', () => {
    expect(visibleFleetPlayerIds(players, 8, {})).toEqual([8, 9, 10])
    expect(visibleFleetPlayerIds(players, 8, { '8': false, '10': false })).toEqual([9])
  })
})
