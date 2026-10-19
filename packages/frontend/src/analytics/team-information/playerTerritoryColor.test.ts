import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  buildPlayerColorPaintSnapshot,
  defaultPlayerColorPaintSnapshotInputs,
  PLAYER_COLOR_PRESET,
} from '../../lib/playerColor'
import { PLAYER_TERRITORY_KIND } from './kinds'
import {
  applyPlayerTerritoryFillColors,
  playerTerritoryFillColor,
} from './playerTerritoryColor'

function playerOverlay(playerId: number): MapRegionOverlay {
  return {
    kind: PLAYER_TERRITORY_KIND,
    id: `player-territory:${playerId}:0`,
    fillColor: '#000000',
    fillOpacity: 0.35,
    fillPattern: 'solid',
    playerId,
    geometry: {
      type: 'boundary',
      vertices: [
        { x: 0, y: 0 },
        { x: 1, y: 0 },
        { x: 0, y: 1 },
      ],
      edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }],
    },
  }
}

describe('playerTerritoryFillColor', () => {
  it('uses the preset and an override, ignoring diplomacy color mode', () => {
    const snapshot = buildPlayerColorPaintSnapshot({
      ...defaultPlayerColorPaintSnapshotInputs(),
      mode: 'diplomacy_family',
      overrides: { '3': '#112233' },
      viewpointPlayerId: 1,
      familyBaseColor: '#336699',
    })
    expect(playerTerritoryFillColor(3, snapshot)).toBe('#112233')
    expect(playerTerritoryFillColor(1, snapshot)).toBe(PLAYER_COLOR_PRESET[1])
    const painted = applyPlayerTerritoryFillColors(
      [playerOverlay(3), playerOverlay(1)],
      snapshot
    )
    expect(painted.map((overlay) => overlay.fillColor)).toEqual(['#112233', PLAYER_COLOR_PRESET[1]])
    expect(painted.every((overlay) => overlay.fillPattern === 'solid')).toBe(true)
  })
})
