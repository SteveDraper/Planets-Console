import { describe, expect, it } from 'vitest'
import {
  defaultCartographyLayerVisibility,
  EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
} from './layers'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
} from './clusterOutlineDisplayMode'
import { defaultStellarCartographyMapUiConfig } from './mapUiConfig'
import {
  areCartographyWormholesShown,
  filterCartographyOverlayCircles,
  filterWormholeEdgesForCartographyConfig,
} from './overlayDisplayFilter'

const baseConfig = {
  ...defaultStellarCartographyMapUiConfig(),
  settingsGates: {
    ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
    nebulae: true,
    ionStorms: true,
    debrisDiskBorders: true,
    wormholes: true,
    starClusters: true,
  },
  wormholeDisplayMode: 'always' as const,
  starClusterDisplayMode: defaultStarClusterDisplayMode(),
  neutronClusterDisplayMode: defaultNeutronClusterDisplayMode(),
}

describe('filterCartographyOverlayCircles', () => {
  it('filters by layer visibility toggle', () => {
    const circles = filterCartographyOverlayCircles(
      [
        {
          layer: 'nebulae',
          id: 'neb-1',
          x: 1,
          y: 2,
          radius: 10,
        },
        {
          layer: 'ion-storms',
          id: 'is-1',
          x: 3,
          y: 4,
          radius: 5,
          voltage: 120,
          class: 3,
          heading: 90,
          warp: 6,
        },
      ],
      {
        ...baseConfig,
        layerVisibility: {
          ...defaultCartographyLayerVisibility(),
          nebulae: false,
        },
      }
    )

    expect(circles).toHaveLength(1)
    expect(circles[0]?.layer).toBe('ion-storms')
  })

  it('filters debris disk borders when the settings gate is off', () => {
    const circles = filterCartographyOverlayCircles(
      [
        {
          layer: 'debris-disks',
          id: 'dd-1',
          x: 100,
          y: 200,
          radius: 37,
        },
      ],
      {
        ...baseConfig,
        settingsGates: {
          ...baseConfig.settingsGates,
          debrisDiskBorders: false,
        },
      }
    )

    expect(circles).toHaveLength(0)
  })

  it('omits star cluster overlay circles when display mode is off', () => {
    const circles = filterCartographyOverlayCircles(
      [
        {
          layer: 'star-clusters',
          id: 'star-1',
          x: 100,
          y: 200,
          radius: 5,
          temp: 10000,
          mass: 10000,
          name: 'Solo',
        },
      ],
      {
        ...baseConfig,
        starClusterDisplayMode: 'off',
      }
    )

    expect(circles).toHaveLength(0)
  })
})

describe('areCartographyWormholesShown', () => {
  it('returns false when wormhole display mode is off', () => {
    expect(
      areCartographyWormholesShown({
        ...baseConfig,
        wormholeDisplayMode: 'off',
      })
    ).toBe(false)
  })

  it('returns true when wormholes are enabled', () => {
    expect(areCartographyWormholesShown(baseConfig)).toBe(true)
  })
})

describe('filterWormholeEdgesForCartographyConfig', () => {
  const wormholeEdge = {
    source: 'stellar-cartography:wh-1',
    target: 'stellar-cartography:wh-2',
    layer: 'wormholes' as const,
  }
  const normalEdge = { source: 'base:1', target: 'base:2' }

  it('removes wormhole edges when the settings gate is off', () => {
    const edges = filterWormholeEdgesForCartographyConfig(
      [normalEdge, wormholeEdge],
      {
        ...baseConfig,
        settingsGates: {
          ...baseConfig.settingsGates,
          wormholes: false,
        },
      },
      null
    )
    expect(edges).toEqual([normalEdge])
  })

  it('keeps wormhole edges when the gate is on and display mode is always', () => {
    const edges = filterWormholeEdgesForCartographyConfig(
      [normalEdge, wormholeEdge],
      baseConfig,
      null
    )
    expect(edges).toEqual([normalEdge, wormholeEdge])
  })
})
