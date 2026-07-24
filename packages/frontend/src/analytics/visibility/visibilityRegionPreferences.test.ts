import { describe, expect, it } from 'vitest'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { defaultVisibilityKindPreferences } from './kinds'
import { applyVisibilityRegionPreferences } from './visibilityRegionPreferences'

function overlay(kind: string, fillColor: string): MapRegionOverlay {
  return {
    kind,
    id: `id-${kind}`,
    fillColor,
    fillOpacity: 0.28,
    disks: [{ x: 0, y: 0, radius: 10 }],
    patches: [],
  }
}

describe('applyVisibilityRegionPreferences', () => {
  it('drops disabled kinds and recolors enabled ones', () => {
    const prefs = defaultVisibilityKindPreferences()
    prefs['ship-scan'].enabled = false
    prefs['active-sensor-sweep'].fillColor = '#ff0000'
    const out = applyVisibilityRegionPreferences(
      [
        overlay('ship-scan', '#38bdf8'),
        overlay('active-sensor-sweep', '#a78bfa'),
        overlay('potential-sensor-sweep', '#fbbf24'),
        overlay('other', '#00ff00'),
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
})
