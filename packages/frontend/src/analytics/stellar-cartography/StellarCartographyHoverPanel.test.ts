import { describe, expect, it } from 'vitest'
import { buildStellarCartographyHoverLines } from './StellarCartographyHoverPanel'
import { cartographyVisibilityPolicy } from './cartographyVisibilityPolicy'
import { defaultStellarCartographyMapUiConfig } from './mapUiConfig'
import { defaultCartographyLayerVisibility } from './layers'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
} from './clusterOutlineDisplayMode'
import { defaultWormholeDisplayMode } from './wormholeDisplayMode'

const settingsGates = {
  debrisDiskBorders: true,
  starClusters: true,
  neutronClusters: true,
  nebulae: true,
  ionStorms: true,
  wormholes: true,
  blackHoles: true,
}

const baseConfig = {
  ...defaultStellarCartographyMapUiConfig(),
  settingsGates,
  wormholeDisplayMode: defaultWormholeDisplayMode(),
  starClusterDisplayMode: defaultStarClusterDisplayMode(),
  neutronClusterDisplayMode: defaultNeutronClusterDisplayMode(),
}

function policyFor(overrides: Partial<typeof baseConfig> = {}) {
  return cartographyVisibilityPolicy({ ...baseConfig, ...overrides })
}

describe('buildStellarCartographyHoverLines', () => {
  it('combines overlapping cartography features into one stacked line list', () => {
    const lines = buildStellarCartographyHoverLines(
      [
        { layer: 'nebulae', lines: ['Zoie', '72 ly'] },
        { layer: 'star-clusters', lines: ['Gores — radiation 42'] },
      ],
      null,
      policyFor({
        layerVisibility: defaultCartographyLayerVisibility(),
      })
    )
    expect(lines).toEqual(['Zoie nebula, visibility 72 ly', 'Gores star cluster — radiation 42'])
  })

  it('appends wormhole hover text to the same stack', () => {
    const lines = buildStellarCartographyHoverLines(
      [{ layer: 'nebulae', lines: ['Zoie', '80 ly'] }],
      ['stability: 80', 'wormhole to (1200, 2400)'],
      policyFor({
        layerVisibility: defaultCartographyLayerVisibility(),
      })
    )
    expect(lines).toEqual([
      'Zoie nebula, visibility 80 ly',
      'stability: 80',
      'wormhole to (1200, 2400)',
    ])
  })

  it('hides star cluster hover lines when that layer is off', () => {
    const lines = buildStellarCartographyHoverLines(
      [{ layer: 'star-clusters', lines: ['Gores — radiation 42'] }],
      null,
      policyFor({
        starClusterDisplayMode: 'off',
      })
    )
    expect(lines).toEqual([])
  })
})
