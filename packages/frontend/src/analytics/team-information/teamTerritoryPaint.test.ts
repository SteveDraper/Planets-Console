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
  omitHiddenTeamTerritoryOverlays,
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

describe('omitHiddenTeamTerritoryOverlays', () => {
  const team4 = boundary(TEAM_TERRITORY_KIND, 'team-territory:4:0', { leagueTeamId: 4 })
  const team9 = boundary(TEAM_TERRITORY_OWNED_ONLY_KIND, 'team-territory-owned-only:9:0', {
    leagueTeamId: 9,
  })
  const player = boundary(PLAYER_TERRITORY_KIND, 'player-territory:1:0', { playerId: 1 })
  const shipScan = boundary('ship-scan', 'ship-scan')
  const overlays = [shipScan, team4, team9, player]

  it('returns the same list when no league team is hidden', () => {
    expect(omitHiddenTeamTerritoryOverlays(overlays, [])).toBe(overlays)
  })

  it('drops hidden league teams and keeps other teams and non-team overlays', () => {
    const out = omitHiddenTeamTerritoryOverlays(overlays, [4])
    expect(out.map((overlay) => overlay.id)).toEqual([
      'ship-scan',
      'team-territory-owned-only:9:0',
      'player-territory:1:0',
    ])
  })
})
