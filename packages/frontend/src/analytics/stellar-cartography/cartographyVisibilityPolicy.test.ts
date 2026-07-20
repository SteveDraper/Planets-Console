import { describe, expect, it } from 'vitest'
import type { StellarCartographySampleEntry } from '../../api/bff'
import {
  defaultCartographyLayerVisibility,
  EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
} from './layers'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
} from './clusterOutlineDisplayMode'
import { defaultStellarCartographyMapUiConfig } from './mapUiConfig'
import { cartographyVisibilityPolicy } from './cartographyVisibilityPolicy'

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

describe('cartographyVisibilityPolicy', () => {
  describe('overlayCircles', () => {
    it('filters by layer visibility toggle', () => {
      const policy = cartographyVisibilityPolicy({
        ...baseConfig,
        layerVisibility: {
          ...defaultCartographyLayerVisibility(),
          nebulae: false,
        },
      })

      const circles = policy.overlayCircles([
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
      ])

      expect(circles).toHaveLength(1)
      expect(circles[0]?.layer).toBe('ion-storms')
    })

    it('filters debris disk borders when the settings gate is off', () => {
      const policy = cartographyVisibilityPolicy({
        ...baseConfig,
        settingsGates: {
          ...baseConfig.settingsGates,
          debrisDiskBorders: false,
        },
      })

      expect(
        policy.overlayCircles([
          {
            layer: 'debris-disks',
            id: 'dd-1',
            x: 100,
            y: 200,
            radius: 37,
          },
        ])
      ).toHaveLength(0)
    })

    it('omits star cluster overlay circles when display mode is off', () => {
      const policy = cartographyVisibilityPolicy({
        ...baseConfig,
        starClusterDisplayMode: 'off',
      })

      expect(
        policy.overlayCircles([
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
        ])
      ).toHaveLength(0)
    })
  })

  describe('sampleEntries', () => {
    it('uses the same layer gates as overlay circles', () => {
      const policy = cartographyVisibilityPolicy({
        ...baseConfig,
        layerVisibility: {
          ...defaultCartographyLayerVisibility(),
          nebulae: false,
        },
      })

      const entries = policy.sampleEntries([
        { layer: 'nebulae', lines: ['Zoie', '72 ly'] },
        { layer: 'ion-storms', lines: ['Storm'] },
        { layer: 'not-a-layer', lines: ['skip'] },
      ] as unknown as StellarCartographySampleEntry[])

      expect(entries).toEqual([{ layer: 'ion-storms', lines: ['Storm'] }])
    })
  })

  describe('mapFrameParts', () => {
    const wormholeNode = {
      id: 'stellar-cartography:wh-1',
      label: '',
      x: 10,
      y: 20,
    }
    const planetNode = { id: 'base-map:1', label: 'A', x: 0, y: 0 }
    const wormholeEdge = {
      source: 'stellar-cartography:wh-1',
      target: 'stellar-cartography:wh-2',
      layer: 'wormholes' as const,
    }

    it('omits wormhole nodes and artifacts when wormholes are off', () => {
      const data = {
        nodes: [planetNode, wormholeNode],
        edges: [wormholeEdge],
        routeWaypoints: [],
        overlayCircles: [],
        regionOverlays: [],
        wormholeUnknownEntrances: [{ x: 50, y: 60 }],
      }
      const policy = cartographyVisibilityPolicy({
        ...baseConfig,
        wormholeDisplayMode: 'off',
      })
      const parts = policy.mapFrameParts(data)

      expect(parts.nodes.map((n) => n.id)).toEqual(['base-map:1'])
      expect(parts.baseEdges).toEqual([])
      expect(parts.wormholeUnknownEntrances).toEqual([])
      expect(parts.wormholeEndpoints).toEqual([])
      expect(parts.wormholeEndpointHoverByCell.size).toBe(0)
    })

    it('keeps wormhole routing data in the frame when wormholes are shown', () => {
      const data = {
        nodes: [planetNode, wormholeNode],
        edges: [wormholeEdge],
        routeWaypoints: [],
        overlayCircles: [],
        regionOverlays: [],
        wormholeUnknownEntrances: [{ x: 50, y: 60 }],
      }
      const parts = cartographyVisibilityPolicy(baseConfig).mapFrameParts(data)

      expect(parts.nodes).toHaveLength(2)
      expect(parts.baseEdges).toEqual([wormholeEdge])
      expect(parts.wormholeUnknownEntrances).toEqual([{ x: 50, y: 60 }])
      expect(parts.wormholeEndpoints.length).toBeGreaterThan(0)
    })
  })

  describe('areWormholesShown', () => {
    it('returns false when wormhole display mode is off', () => {
      expect(
        cartographyVisibilityPolicy({
          ...baseConfig,
          wormholeDisplayMode: 'off',
        }).areWormholesShown()
      ).toBe(false)
    })

    it('returns true when wormholes are enabled', () => {
      expect(cartographyVisibilityPolicy(baseConfig).areWormholesShown()).toBe(true)
    })
  })

  describe('mapEdges', () => {
    const wormholeEdge = {
      source: 'stellar-cartography:wh-1',
      target: 'stellar-cartography:wh-2',
      layer: 'wormholes' as const,
    }
    const normalEdge = { source: 'base:1', target: 'base:2' }

    it('removes wormhole edges when the settings gate is off', () => {
      const policy = cartographyVisibilityPolicy({
        ...baseConfig,
        settingsGates: {
          ...baseConfig.settingsGates,
          wormholes: false,
        },
      })

      expect(policy.mapEdges([normalEdge, wormholeEdge], null)).toEqual([normalEdge])
    })

    it('keeps wormhole edges when the gate is on and display mode is always', () => {
      const policy = cartographyVisibilityPolicy(baseConfig)
      expect(policy.mapEdges([normalEdge, wormholeEdge], null)).toEqual([
        normalEdge,
        wormholeEdge,
      ])
    })
  })
})
