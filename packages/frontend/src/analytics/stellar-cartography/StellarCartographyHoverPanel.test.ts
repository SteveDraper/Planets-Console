import { describe, expect, it } from 'vitest'
import { buildStellarCartographyHoverLines } from './StellarCartographyHoverPanel'
import { defaultCartographyLayerVisibility } from './layers'
import { defaultWormholeDisplayMode } from './wormholeDisplayMode'

const settingsGates = {
  debrisDiskBorders: true,
  starClusters: true,
  nebulae: true,
  ionStorms: true,
  wormholes: true,
  blackHoles: true,
}

describe('buildStellarCartographyHoverLines', () => {
  it('combines overlapping cartography features into one stacked line list', () => {
    const lines = buildStellarCartographyHoverLines(
      [
        { layer: 'nebulae', lines: ['Zoie', '72 ly'] },
        { layer: 'star-clusters', lines: ['Gores — radiation 42'] },
      ],
      null,
      defaultCartographyLayerVisibility(),
      settingsGates,
      defaultWormholeDisplayMode()
    )
    expect(lines).toEqual(['Zoie nebula, visibility 72 ly', 'Gores star cluster — radiation 42'])
  })

  it('appends wormhole hover text to the same stack', () => {
    const lines = buildStellarCartographyHoverLines(
      [{ layer: 'nebulae', lines: ['Zoie', '80 ly'] }],
      ['stability: 80', 'wormhole to (1200, 2400)'],
      defaultCartographyLayerVisibility(),
      settingsGates,
      defaultWormholeDisplayMode()
    )
    expect(lines).toEqual([
      'Zoie nebula, visibility 80 ly',
      'stability: 80',
      'wormhole to (1200, 2400)',
    ])
  })
})
