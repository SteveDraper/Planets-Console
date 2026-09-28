import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { isVisibilityRegionKind } from '../visibility/kinds'
import { TEAM_TERRITORY_KIND, TEAM_TERRITORY_OWNED_ONLY_KIND } from './kinds'
import { applyTeamTerritorySiteSet, mapRegionOverlaysForPaint } from './teamTerritoryPaint'

function boundary(kind: string, id: string): MapRegionOverlay {
  return {
    kind,
    id,
    fillColor: '#38bdf8',
    fillOpacity: 0.35,
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

describe('applyTeamTerritorySiteSet', () => {
  const allPlanets = boundary(TEAM_TERRITORY_KIND, 'team-territory:4:0')
  const ownedOnly = boundary(TEAM_TERRITORY_OWNED_ONLY_KIND, 'team-territory-owned-only:4:0')
  const shipScan = boundary('ship-scan', 'ship-scan')

  it('keeps the all-planets kind when owned planets only is off', () => {
    const out = applyTeamTerritorySiteSet([allPlanets, ownedOnly, shipScan], false)
    expect(out.map((overlay) => overlay.kind)).toEqual([TEAM_TERRITORY_KIND, 'ship-scan'])
  })

  it('keeps the owned-planets kind when owned planets only is on', () => {
    const out = applyTeamTerritorySiteSet([allPlanets, ownedOnly, shipScan], true)
    expect(out.map((overlay) => overlay.kind)).toEqual([
      TEAM_TERRITORY_OWNED_ONLY_KIND,
      'ship-scan',
    ])
  })
})

describe('mapRegionOverlaysForPaint', () => {
  it('does not send team-territory kinds through the non-team painter', () => {
    expect(isVisibilityRegionKind(TEAM_TERRITORY_KIND)).toBe(false)
    expect(isVisibilityRegionKind(TEAM_TERRITORY_OWNED_ONLY_KIND)).toBe(false)
    const allPlanets = boundary(TEAM_TERRITORY_KIND, 'team-territory:4:0')
    const ownedOnly = boundary(TEAM_TERRITORY_OWNED_ONLY_KIND, 'team-territory-owned-only:4:0')
    const shipScan = boundary('ship-scan', 'ship-scan')
    const seen: string[] = []
    const out = mapRegionOverlaysForPaint(
      [shipScan, allPlanets, ownedOnly],
      false,
      (nonTeam) => {
        seen.push(...nonTeam.map((overlay) => overlay.kind))
        return nonTeam.map((overlay) =>
          overlay.kind === 'ship-scan' ? { ...overlay, fillColor: '#ff0000' } : overlay
        )
      }
    )
    expect(seen).toEqual(['ship-scan'])
    expect(out.map((overlay) => overlay.id)).toEqual(['ship-scan', 'team-territory:4:0'])
    expect(out[0]?.fillColor).toBe('#ff0000')
    expect(out[1]).toBe(allPlanets)
  })
})
