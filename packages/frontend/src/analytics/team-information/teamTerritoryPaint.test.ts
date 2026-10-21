import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { isVisibilityRegionKind } from '../visibility/kinds'
import {
  PLAYER_TERRITORY_KIND,
  PLAYER_TERRITORY_OWNED_ONLY_KIND,
  TEAM_TERRITORY_KIND,
  TEAM_TERRITORY_OWNED_ONLY_KIND,
} from './kinds'
import {
  applyTerritoryKindFilter,
  mapRegionOverlaysForPaint,
  omitHiddenTerritoryOverlays,
  territoryOverlaysForHighlight,
} from './teamTerritoryPaint'

function boundary(
  kind: string,
  id: string,
  ids?: { leagueTeamId?: number; playerId?: number }
): MapRegionOverlay {
  return {
    kind,
    id,
    fillColor: '#38bdf8',
    fillOpacity: 0.35,
    ...(ids?.leagueTeamId != null ? { leagueTeamId: ids.leagueTeamId } : {}),
    ...(ids?.playerId != null ? { playerId: ids.playerId } : {}),
    geometry: {
      type: 'boundary',
      vertices: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 0, y: 10 },
      ],
      edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }],
    },
  }
}

describe('applyTerritoryKindFilter', () => {
  const allPlanets = boundary(TEAM_TERRITORY_KIND, 'team-territory:4:0')
  const ownedOnly = boundary(TEAM_TERRITORY_OWNED_ONLY_KIND, 'team-territory-owned-only:4:0')
  const playerAll = boundary(PLAYER_TERRITORY_KIND, 'player-territory:1:0', { playerId: 1 })
  const playerOwned = boundary(PLAYER_TERRITORY_OWNED_ONLY_KIND, 'player-territory-owned-only:1:0', {
    playerId: 1,
  })
  const shipScan = boundary('ship-scan', 'ship-scan')
  const overlays = [allPlanets, ownedOnly, playerAll, playerOwned, shipScan]

  it.each([
    [true, false, TEAM_TERRITORY_KIND],
    [true, true, TEAM_TERRITORY_OWNED_ONLY_KIND],
    [false, false, PLAYER_TERRITORY_KIND],
    [false, true, PLAYER_TERRITORY_OWNED_ONLY_KIND],
  ] as const)(
    'keeps one territory kind for byTeam=%s ownedPlanetsOnly=%s',
    (byTeam, ownedPlanetsOnly, kept) => {
      const out = applyTerritoryKindFilter(overlays, byTeam, ownedPlanetsOnly)
      expect(out.map((overlay) => overlay.kind)).toEqual([kept, 'ship-scan'])
    }
  )
})

describe('mapRegionOverlaysForPaint', () => {
  it('does not send territory kinds through the non-territory painter', () => {
    expect(isVisibilityRegionKind(TEAM_TERRITORY_KIND)).toBe(false)
    expect(isVisibilityRegionKind(TEAM_TERRITORY_OWNED_ONLY_KIND)).toBe(false)
    expect(isVisibilityRegionKind(PLAYER_TERRITORY_KIND)).toBe(false)
    expect(isVisibilityRegionKind(PLAYER_TERRITORY_OWNED_ONLY_KIND)).toBe(false)
    const allPlanets = boundary(TEAM_TERRITORY_KIND, 'team-territory:4:0')
    const ownedOnly = boundary(TEAM_TERRITORY_OWNED_ONLY_KIND, 'team-territory-owned-only:4:0')
    const playerAll = boundary(PLAYER_TERRITORY_KIND, 'player-territory:1:0', { playerId: 1 })
    const shipScan = boundary('ship-scan', 'ship-scan')
    const seen: string[] = []
    const out = mapRegionOverlaysForPaint(
      [shipScan, allPlanets, ownedOnly, playerAll],
      false,
      false,
      (nonTerritory) => {
        seen.push(...nonTerritory.map((overlay) => overlay.kind))
        return nonTerritory.map((overlay) =>
          overlay.kind === 'ship-scan' ? { ...overlay, fillColor: '#ff0000' } : overlay
        )
      }
    )
    expect(seen).toEqual(['ship-scan'])
    expect(out.map((overlay) => overlay.id)).toEqual(['ship-scan', 'player-territory:1:0'])
    expect(out[0]?.fillColor).toBe('#ff0000')
    expect(out[1]).toBe(playerAll)
  })
})

describe('omitHiddenTerritoryOverlays', () => {
  const team4 = boundary(TEAM_TERRITORY_KIND, 'team-territory:4:0', { leagueTeamId: 4 })
  const team9 = boundary(TEAM_TERRITORY_OWNED_ONLY_KIND, 'team-territory-owned-only:9:0', {
    leagueTeamId: 9,
  })
  const player = boundary(PLAYER_TERRITORY_KIND, 'player-territory:1:0', { playerId: 1 })
  const playerOwned = boundary(
    PLAYER_TERRITORY_OWNED_ONLY_KIND,
    'player-territory-owned-only:1:0',
    { playerId: 1 }
  )
  const otherPlayer = boundary(PLAYER_TERRITORY_KIND, 'player-territory:2:0', { playerId: 2 })
  const shipScan = boundary('ship-scan', 'ship-scan')
  const overlays = [shipScan, team4, team9, player, playerOwned, otherPlayer]

  it('returns the same list when nothing is hidden', () => {
    expect(omitHiddenTerritoryOverlays(overlays, [], [])).toBe(overlays)
  })

  it('drops hidden league teams and keeps player overlays', () => {
    const out = omitHiddenTerritoryOverlays(overlays, [4], [])
    expect(out.map((overlay) => overlay.id)).toEqual([
      'ship-scan',
      'team-territory-owned-only:9:0',
      'player-territory:1:0',
      'player-territory-owned-only:1:0',
      'player-territory:2:0',
    ])
    expect(out[2]).toBe(player)
  })

  it('drops a hidden player on both site sets and keeps team overlays', () => {
    const out = omitHiddenTerritoryOverlays(overlays, [], [1])
    expect(out.map((overlay) => overlay.id)).toEqual([
      'ship-scan',
      'team-territory:4:0',
      'team-territory-owned-only:9:0',
      'player-territory:2:0',
    ])
    expect(out[1]).toBe(team4)
    expect(out[3]).toBe(otherPlayer)
  })
})

describe('territoryOverlaysForHighlight', () => {
  const team4 = boundary(TEAM_TERRITORY_KIND, 'team-territory:4:0', { leagueTeamId: 4 })
  const team4Owned = boundary(TEAM_TERRITORY_OWNED_ONLY_KIND, 'team-territory-owned-only:4:0', {
    leagueTeamId: 4,
  })
  const player4 = boundary(PLAYER_TERRITORY_KIND, 'player-territory:4:0', { playerId: 4 })
  const player1 = boundary(PLAYER_TERRITORY_KIND, 'player-territory:1:0', { playerId: 1 })
  const player1Owned = boundary(
    PLAYER_TERRITORY_OWNED_ONLY_KIND,
    'player-territory-owned-only:1:0',
    { playerId: 1 }
  )
  const overlays = [team4, team4Owned, player4, player1, player1Owned]

  it('returns nothing when nothing is hovered', () => {
    expect(territoryOverlaysForHighlight(overlays, null, true)).toEqual([])
  })

  it('outlines the hovered league team, including both team kinds', () => {
    const out = territoryOverlaysForHighlight(overlays, { partition: 'team', id: 4 }, true)
    expect(out.map((overlay) => overlay.id)).toEqual([
      'team-territory:4:0',
      'team-territory-owned-only:4:0',
    ])
  })

  it('does not apply a hovered league team while By team is off', () => {
    expect(
      territoryOverlaysForHighlight(overlays, { partition: 'team', id: 4 }, false)
    ).toEqual([])
  })

  it('outlines the hovered player and not the league team with the same id', () => {
    const out = territoryOverlaysForHighlight(overlays, { partition: 'player', id: 4 }, false)
    expect(out.map((overlay) => overlay.id)).toEqual(['player-territory:4:0'])
  })

  it('does not apply a hovered player while By team is on', () => {
    expect(
      territoryOverlaysForHighlight(overlays, { partition: 'player', id: 1 }, true)
    ).toEqual([])
  })

  it('outlines both player kinds for the hovered player', () => {
    const out = territoryOverlaysForHighlight(overlays, { partition: 'player', id: 1 }, false)
    expect(out.map((overlay) => overlay.id)).toEqual([
      'player-territory:1:0',
      'player-territory-owned-only:1:0',
    ])
  })
})
