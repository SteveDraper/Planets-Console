import { describe, expect, it } from 'vitest'
import {
  buildPlayerColorPaintSnapshot,
  defaultColorForPlayerId,
  defaultPlayerColorPaintSnapshotInputs,
} from '../../lib/playerColor'
import { playerTerritoryLegendLabel, playerTerritoryLegendRows } from './playerLegend'

describe('playerTerritoryLegendRows', () => {
  it('uses the roster username, the numeric id, and the per-player palette', () => {
    const snapshot = buildPlayerColorPaintSnapshot(defaultPlayerColorPaintSnapshotInputs())
    const rows = playerTerritoryLegendRows(
      [{ playerId: 2 }, { playerId: 9 }],
      new Map([[2, 'alice']]),
      snapshot
    )
    expect(rows).toEqual([
      { playerId: 2, name: 'alice', fillColor: defaultColorForPlayerId(2) },
      { playerId: 9, name: null, fillColor: defaultColorForPlayerId(9) },
    ])
    expect(playerTerritoryLegendLabel(2, new Map([[2, 'alice']]))).toBe('alice')
    expect(playerTerritoryLegendLabel(9, new Map())).toBe('9')
  })
})
