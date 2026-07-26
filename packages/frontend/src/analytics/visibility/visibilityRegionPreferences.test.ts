import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { defaultVisibilityKindPreferences } from './kinds'
import { applyVisibilityRegionPreferences } from './visibilityRegionPreferences'

function coverageOverlay(kind: string, fillColor: string): MapRegionOverlay {
  return {
    kind,
    id: `id-${kind}`,
    fillColor,
    fillOpacity: 0.28,
    geometry: {
      type: 'coverage',
      disks: [{ x: 0, y: 0, radius: 10 }],
      patches: [],
    },
  }
}

function boundaryOverlay(kind: string, fillColor: string): MapRegionOverlay {
  return {
    kind,
    id: `id-${kind}`,
    fillColor,
    fillOpacity: 0.2,
    geometry: {
      type: 'boundary',
      vertices: [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 0, y: 10 },
      ],
      edges: [{ type: 'line' }, { type: 'line' }, { type: 'line' }],
    },
    isPinned: false,
  }
}

describe('applyVisibilityRegionPreferences', () => {
  it('drops disabled kinds and recolors enabled ones', () => {
    const prefs = defaultVisibilityKindPreferences()
    prefs['ship-scan'].enabled = false
    prefs['active-sensor-sweep'].fillColor = '#ff0000'
    const out = applyVisibilityRegionPreferences(
      [
        coverageOverlay('ship-scan', '#38bdf8'),
        coverageOverlay('active-sensor-sweep', '#a78bfa'),
        coverageOverlay('potential-sensor-sweep', '#fbbf24'),
        coverageOverlay('other', '#00ff00'),
      ],
      prefs
    )
    expect(out.map((o) => o.kind)).toEqual([
      'active-sensor-sweep',
      'potential-sensor-sweep',
      'other',
    ])
    expect(out[0].fillColor).toBe('#ff0000')
    expect(out[1].fillColor).toBe('#fbbf24')
  })

  it('passes non-visibility overlays through even when all visibility kinds are off', () => {
    const prefs = defaultVisibilityKindPreferences()
    for (const kind of Object.keys(prefs) as (keyof typeof prefs)[]) {
      prefs[kind].enabled = false
    }
    const homeworld = boundaryOverlay('homeworld-sector', '#f97316')
    const out = applyVisibilityRegionPreferences(
      [
        coverageOverlay('ship-scan', '#38bdf8'),
        homeworld,
        coverageOverlay('active-minefield-detect', '#a3e635'),
      ],
      prefs
    )
    expect(out).toEqual([homeworld])
  })

  it('does not recolor non-visibility overlays', () => {
    const prefs = defaultVisibilityKindPreferences()
    prefs['ship-scan'].fillColor = '#ff0000'
    const homeworld = boundaryOverlay('homeworld-sector', '#f97316')
    const out = applyVisibilityRegionPreferences([homeworld], prefs)
    expect(out[0]).toBe(homeworld)
    expect(out[0].fillColor).toBe('#f97316')
  })
})
