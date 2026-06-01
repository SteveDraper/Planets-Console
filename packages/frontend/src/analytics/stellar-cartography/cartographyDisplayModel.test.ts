import { describe, expect, it } from 'vitest'
import type { CombinedMapData } from '../../api/bff'
import { STELLAR_CARTOGRAPHY_ANALYTIC_ID } from '../mapAnalyticIds'
import {
  buildCartographyMapFrame,
  cartographyMapEdges,
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

  it('dedupes wormhole nodes at the same coordinates', () => {
    const nodes = [
      { id: `${SC_PREFIX}wh-1`, label: '', x: 10, y: 20 },
      { id: `${SC_PREFIX}wh-2`, label: '', x: 10, y: 20 },
      { id: 'base-map:planet-1', label: 'Planet', x: 30, y: 40 },
    ] satisfies CombinedMapData['nodes']
    const unknownEntrances = [
      { x: 10, y: 20 },
      { x: 50, y: 60 },
    ] satisfies CombinedMapData['wormholeUnknownEntrances']

    expect(collectWormholeEndpoints(nodes, unknownEntrances)).toEqual([
      { x: 10, y: 20 },
      { x: 50, y: 60 },
    ])
  })
})

describe('buildCartographyMapFrame and cartographyMapEdges', () => {
  it('applies hover reveal only through cartographyMapEdges, not the static frame', () => {
    const context = cartographyContext({ wormholeDisplayMode: 'on-hover' })
    const frame = buildCartographyMapFrame(sampleData, context)

    expect(frame.baseEdges.some((e) => e.layer === 'wormholes')).toBe(true)
    expect(cartographyMapEdges(frame, context.config, null).every((e) => e.layer !== 'wormholes')).toBe(
      true
    )
    expect(
      cartographyMapEdges(frame, context.config, '10,20').some((e) => e.layer === 'wormholes')
    ).toBe(true)
  })

  it('hides all cartography artifacts when the analytic is disabled', () => {
    const frame = buildCartographyMapFrame(sampleData, undefined)
    const edges = cartographyMapEdges(frame, undefined)

    expect(frame.cartographyEnabled).toBe(false)
    expect(frame.nodes.map((n) => n.id)).toEqual(['base-map:1'])
    expect(edges.every((e) => e.layer !== 'wormholes')).toBe(true)
    expect(frame.overlayCircles).toEqual([])
    expect(frame.wormholeUnknownEntrances).toEqual([])
    expect(frame.wormholeEndpoints).toEqual([])
    expect(frame.wormholeEndpointHoverByCell.size).toBe(0)
  })

  it('filters overlay circles by layer config when cartography is enabled', () => {
    const context = cartographyContext({
      layerVisibility: { ...defaultCartographyLayerVisibility(), nebulae: false },
    })
    const frame = buildCartographyMapFrame(sampleData, context)

    expect(frame.cartographyEnabled).toBe(true)
    expect(frame.overlayCircles.map((c) => c.layer)).toEqual(['black-holes'])
  })

  it('removes wormhole routing nodes and endpoints when the wormhole layer is off', () => {
    const context = cartographyContext({ wormholeDisplayMode: 'off' })
    const frame = buildCartographyMapFrame(sampleData, context)
    const edges = cartographyMapEdges(frame, context.config)

    expect(frame.nodes.map((n) => n.id)).toEqual(['base-map:1'])
    expect(edges.every((e) => e.layer !== 'wormholes')).toBe(true)
    expect(frame.wormholeUnknownEntrances).toEqual([])
    expect(frame.wormholeEndpoints).toEqual([])
    expect(frame.wormholeEndpointHoverByCell.size).toBe(0)
  })

  it('keeps wormhole hover metadata when lines use on-hover reveal', () => {
    const context = cartographyContext({ wormholeDisplayMode: 'on-hover' })
    const frame = buildCartographyMapFrame(sampleData, context)
    const edges = cartographyMapEdges(frame, context.config, null)

    expect(edges.filter((e) => e.layer === 'wormholes')).toEqual([])
    expect(frame.wormholeEndpointHoverByCell.size).toBeGreaterThan(0)
    expect(frame.wormholeEndpoints.length).toBeGreaterThan(0)
  })

  it('reveals wormhole lines for the hovered cell key', () => {
    const context = cartographyContext({ wormholeDisplayMode: 'on-hover' })
    const frame = buildCartographyMapFrame(sampleData, context)
    const edges = cartographyMapEdges(frame, context.config, '10,20')

    expect(edges.some((e) => e.layer === 'wormholes')).toBe(true)
  })
})
