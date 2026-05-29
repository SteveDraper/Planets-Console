import { describe, expect, it } from 'vitest'
import { formatStellarCartographySampleLine } from './sampleTooltipFormat'

describe('formatStellarCartographySampleLine', () => {
  it('formats nebula and ion storm lines for the stacked panel', () => {
    expect(
      formatStellarCartographySampleLine({ layer: 'nebulae', lines: ['Zoie', '94 ly'] })
    ).toBe('Zoie nebula, visibility 94 ly')
    expect(
      formatStellarCartographySampleLine({
        layer: 'ion-storms',
        lines: ['Class 3 Strong', '112 V'],
      })
    ).toBe('Ion storm: Class 3 Strong — 112 V')
    expect(
      formatStellarCartographySampleLine({
        layer: 'star-clusters',
        lines: ['Gores — lethal — temp 28601'],
      })
    ).toBe('Gores star cluster — lethal — temp 28601')
  })
})
