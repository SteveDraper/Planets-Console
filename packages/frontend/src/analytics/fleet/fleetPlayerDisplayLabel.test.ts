import { describe, expect, it } from 'vitest'
import { fleetPlayerDisplayLabel } from './fleetPlayerDisplayLabel'
import { pendingFleetPlayerStreamSlice } from './fleetTablePlayerStreamState'

describe('fleetPlayerDisplayLabel', () => {
  const player = { playerId: 8, name: 'dead', raceName: 'The Solar Federation' }

  it('prefers scoreboard race-player labels for the viewed turn', () => {
    const labels = new Map([[8, 'The Solar Federation (dougp314)']])
    expect(fleetPlayerDisplayLabel(player, labels, undefined)).toBe(
      'The Solar Federation (dougp314)'
    )
  })

  it('falls back to stream player name with shell race when scores labels are absent', () => {
    const streamSlice = {
      ...pendingFleetPlayerStreamSlice(),
      playerName: 'dougp314',
    }
    expect(fleetPlayerDisplayLabel(player, new Map(), streamSlice)).toBe(
      'The Solar Federation (dougp314)'
    )
  })

  it('falls back to shell player name when stream and scores labels are absent', () => {
    expect(fleetPlayerDisplayLabel(player, new Map(), undefined)).toBe(
      'The Solar Federation (dead)'
    )
  })
})
