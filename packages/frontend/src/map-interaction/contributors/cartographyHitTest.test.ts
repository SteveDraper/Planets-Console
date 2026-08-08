import { describe, expect, it } from 'vitest'
import { cartographyVisibilityPolicy } from '../../analytics/stellar-cartography/cartographyVisibilityPolicy'
import { defaultStellarCartographyMapUiConfig } from '../../analytics/stellar-cartography/mapUiConfig'
import { defaultCartographyLayerVisibility } from '../../analytics/stellar-cartography/layers'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
} from '../../analytics/stellar-cartography/clusterOutlineDisplayMode'
import { defaultWormholeDisplayMode } from '../../analytics/stellar-cartography/wormholeDisplayMode'
import type { StellarCartographyMapContext } from '../../analytics/stellar-cartography/mapUiConfig'
import { cartographySampleLinesFromEntries } from './cartographyHitTest'

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

function cartographyFor(
  overrides: Partial<typeof baseConfig> = {}
): StellarCartographyMapContext {
  const config = { ...baseConfig, ...overrides }
  return {
    config: defaultStellarCartographyMapUiConfig(),
    analyticScope: { gameId: '1', turn: 1, perspective: 1 },
    policy: cartographyVisibilityPolicy(config),
  } as StellarCartographyMapContext
}

describe('cartographySampleLinesFromEntries', () => {
  it('combines overlapping cartography features into one stacked line list', () => {
    const lines = cartographySampleLinesFromEntries(
      [
        { layer: 'nebulae', lines: ['Zoie', '72 ly'] },
        { layer: 'star-clusters', lines: ['Gores — radiation 42'] },
      ],
      cartographyFor({
        layerVisibility: defaultCartographyLayerVisibility(),
      })
    )
    expect(lines).toEqual([
      'Zoie nebula, visibility 72 ly',
      'Gores star cluster — radiation 42',
    ])
  })

  it('hides star cluster hover lines when that layer is off', () => {
    const lines = cartographySampleLinesFromEntries(
      [{ layer: 'star-clusters', lines: ['Gores — radiation 42'] }],
      cartographyFor({
        starClusterDisplayMode: 'off',
      })
    )
    expect(lines).toEqual([])
  })
})
