import { describe, expect, it } from 'vitest'
import type { CombinedMapData } from '../../api/bff'
import { STELLAR_CARTOGRAPHY_ANALYTIC_ID } from '../mapAnalyticIds'
import {
  buildCartographyDisplayModel,
  collectWormholeEndpoints,
} from './cartographyDisplayModel'
import {
  defaultCartographyLayerVisibility,
  EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
} from './layers'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
} from './clusterOutlineDisplayMode'
import type { StellarCartographyMapContext } from './mapUiConfig'
import { defaultStellarCartographyMapUiConfig } from './mapUiConfig'

const SC_PREFIX = `${STELLAR_CARTOGRAPHY_ANALYTIC_ID}:`

const sampleData = {
  nodes: [
    { id: 'base-map:1', label: 'Planet', x: 1, y: 2, planet: { id: 1 } },
    { id: `${SC_PREFIX}wh-1`, label: '', x: 10, y: 20 },
    { id: `${SC_PREFIX}wh-2`, label: '', x: 30, y: 40 },
  ],
  edges: [
    { source: 'base-map:1', target: 'base-map:2' },
    {
      source: `${SC_PREFIX}wh-1`,
      target: `${SC_PREFIX}wh-2`,
      layer: 'wormholes' as const,
      sourceGameX: 10,
      sourceGameY: 20,
      targetGameX: 30,
      targetGameY: 40,
      isBidirectional: true,
    },
  ],
  routeWaypoints: [],
  overlayCircles: [
    { layer: 'nebulae' as const, id: 'neb-1', x: 1, y: 2, radius: 10 },
    { layer: 'black-holes' as const, id: 'bh-1', x: 3, y: 4, radius: 5, coreRadius: 1, bandRadius: 1 },
  ],
  wormholeUnknownEntrances: [{ x: 50, y: 60 }],
} satisfies CombinedMapData

function cartographyContext(
  overrides: Partial<StellarCartographyMapContext['config']> = {}
): StellarCartographyMapContext {
  return {
    analyticScope: { gameId: 'g1', turn: 5, perspective: 1 },
    config: {
      ...defaultStellarCartographyMapUiConfig(),
      settingsGates: {
        ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
        nebulae: true,
        blackHoles: true,
        wormholes: true,
      },
      layerVisibility: defaultCartographyLayerVisibility(),
      wormholeDisplayMode: 'always',
      starClusterDisplayMode: defaultStarClusterDisplayMode(),
      neutronClusterDisplayMode: defaultNeutronClusterDisplayMode(),
      ...overrides,
    },
  }
}

describe('collectWormholeEndpoints', () => {
  it('dedupes rendered wormhole nodes and unknown entrances', () => {
    expect(
      collectWormholeEndpoints(sampleData.nodes, sampleData.wormholeUnknownEntrances)
    ).toEqual([
      { x: 10, y: 20 },
      { x: 30, y: 40 },
      { x: 50, y: 60 },
    ])
  })
})

describe('buildCartographyDisplayModel', () => {
  it('hides all cartography artifacts when the analytic is disabled', () => {
    const display = buildCartographyDisplayModel(sampleData, undefined)

    expect(display.cartographyEnabled).toBe(false)
    expect(display.nodes.map((n) => n.id)).toEqual(['base-map:1'])
    expect(display.edges.every((e) => e.layer !== 'wormholes')).toBe(true)
    expect(display.overlayCircles).toEqual([])
    expect(display.wormholeUnknownEntrances).toEqual([])
    expect(display.wormholeEndpoints).toEqual([])
    expect(display.wormholeEndpointHoverByCell.size).toBe(0)
  })

  it('filters overlay circles by layer config when cartography is enabled', () => {
    const display = buildCartographyDisplayModel(
      sampleData,
      cartographyContext({
        layerVisibility: { ...defaultCartographyLayerVisibility(), nebulae: false },
      })
    )

    expect(display.cartographyEnabled).toBe(true)
    expect(display.overlayCircles.map((c) => c.layer)).toEqual(['black-holes'])
  })

  it('removes wormhole routing nodes and endpoints when the wormhole layer is off', () => {
    const display = buildCartographyDisplayModel(
      sampleData,
      cartographyContext({ wormholeDisplayMode: 'off' })
    )

    expect(display.nodes.map((n) => n.id)).toEqual(['base-map:1'])
    expect(display.edges.every((e) => e.layer !== 'wormholes')).toBe(true)
    expect(display.wormholeUnknownEntrances).toEqual([])
    expect(display.wormholeEndpoints).toEqual([])
    expect(display.wormholeEndpointHoverByCell.size).toBe(0)
  })

  it('keeps wormhole hover metadata when lines use on-hover reveal', () => {
    const display = buildCartographyDisplayModel(
      sampleData,
      cartographyContext({ wormholeDisplayMode: 'on-hover' }),
      null
    )

    expect(display.edges.filter((e) => e.layer === 'wormholes')).toEqual([])
    expect(display.wormholeEndpointHoverByCell.size).toBeGreaterThan(0)
    expect(display.wormholeEndpoints.length).toBeGreaterThan(0)
  })

  it('reveals wormhole lines for the hovered cell key', () => {
    const display = buildCartographyDisplayModel(
      sampleData,
      cartographyContext({ wormholeDisplayMode: 'on-hover' }),
      '10,20'
    )

    expect(display.edges.some((e) => e.layer === 'wormholes')).toBe(true)
  })
})
