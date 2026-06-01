import { describe, expect, it } from 'vitest'
import type { CombinedMapData } from '../../api/bff'
import { STELLAR_CARTOGRAPHY_ANALYTIC_ID } from '../mapAnalyticIds'
import {
  buildCartographyDisplay,
  buildCartographyMapFrame,
  cartographyDisplayEdges,
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
import { buildStellarCartographyMapContext, defaultStellarCartographyMapUiConfig } from './mapUiConfig'

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
    {
      layer: 'ion-storms' as const,
      id: 'is-1',
      x: 100,
      y: 200,
      radius: 30,
      class: 2,
      heading: 0,
      warp: 5,
    },
  ],
  wormholeUnknownEntrances: [{ x: 50, y: 60 }],
} satisfies CombinedMapData

function cartographyContext(
  overrides: Partial<StellarCartographyMapContext['config']> = {}
): StellarCartographyMapContext {
  return buildStellarCartographyMapContext(
    {
      ...defaultStellarCartographyMapUiConfig(),
      settingsGates: {
        ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
        nebulae: true,
        blackHoles: true,
        wormholes: true,
        ionStorms: true,
      },
      layerVisibility: defaultCartographyLayerVisibility(),
      wormholeDisplayMode: 'always',
      starClusterDisplayMode: defaultStarClusterDisplayMode(),
      neutronClusterDisplayMode: defaultNeutronClusterDisplayMode(),
      ...overrides,
    },
    { gameId: 'g1', turn: 5, perspective: 1 }
  )
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

describe('buildCartographyDisplay', () => {
  it('applies hover reveal only through edges, not the static frame', () => {
    const context = cartographyContext({ wormholeDisplayMode: 'on-hover' })
    const frame = buildCartographyMapFrame(sampleData, context)

    expect(frame.baseEdges.some((e) => e.layer === 'wormholes')).toBe(true)
    expect(cartographyDisplayEdges(frame, context, null).every((e) => e.layer !== 'wormholes')).toBe(
      true
    )
    expect(
      cartographyDisplayEdges(frame, context, '10,20').some((e) => e.layer === 'wormholes')
    ).toBe(true)
  })

  it('builds frame and edges together via buildCartographyDisplay', () => {
    const context = cartographyContext({ wormholeDisplayMode: 'on-hover' })
    const display = buildCartographyDisplay(sampleData, context, {
      wormholeLineRevealKey: '10,20',
    })

    expect(display.baseEdges.some((e) => e.layer === 'wormholes')).toBe(true)
    expect(display.edges.some((e) => e.layer === 'wormholes')).toBe(true)
  })

  it('hides all cartography artifacts when the analytic is disabled', () => {
    const display = buildCartographyDisplay(sampleData, undefined)

    expect(display.nodes.map((n) => n.id)).toEqual(['base-map:1'])
    expect(display.edges.every((e) => e.layer !== 'wormholes')).toBe(true)
    expect(display.overlayCircles).toEqual([])
    expect(display.wormholeUnknownEntrances).toEqual([])
    expect(display.wormholeEndpoints).toEqual([])
    expect(display.wormholeEndpointHoverByCell.size).toBe(0)
  })

  it('filters overlay circles by layer config when cartography is enabled', () => {
    const context = cartographyContext({
      layerVisibility: { ...defaultCartographyLayerVisibility(), nebulae: false },
    })
    const frame = buildCartographyMapFrame(sampleData, context)

    expect(frame.overlayCircles.map((c) => c.layer)).toEqual(['black-holes', 'ion-storms'])
  })

  it('extrapolates ion storm overlay positions for future turns at display time', () => {
    const context = cartographyContext()
    const frame = buildCartographyMapFrame(sampleData, context, 2)

    expect(frame.overlayCircles.find((c) => c.layer === 'ion-storms')).toMatchObject({
      x: 100,
      y: 250,
    })
    expect(sampleData.overlayCircles.find((c) => c.layer === 'ion-storms')).toMatchObject({
      x: 100,
      y: 200,
    })
  })

  it('removes wormhole routing nodes and endpoints when the wormhole layer is off', () => {
    const context = cartographyContext({ wormholeDisplayMode: 'off' })
    const display = buildCartographyDisplay(sampleData, context)

    expect(display.nodes.map((n) => n.id)).toEqual(['base-map:1'])
    expect(display.edges.every((e) => e.layer !== 'wormholes')).toBe(true)
    expect(display.wormholeUnknownEntrances).toEqual([])
    expect(display.wormholeEndpoints).toEqual([])
    expect(display.wormholeEndpointHoverByCell.size).toBe(0)
  })

  it('keeps wormhole hover metadata when lines use on-hover reveal', () => {
    const context = cartographyContext({ wormholeDisplayMode: 'on-hover' })
    const display = buildCartographyDisplay(sampleData, context)

    expect(display.edges.filter((e) => e.layer === 'wormholes')).toEqual([])
    expect(display.wormholeEndpointHoverByCell.size).toBeGreaterThan(0)
    expect(display.wormholeEndpoints.length).toBeGreaterThan(0)
  })

  it('reveals wormhole lines for the hovered cell key', () => {
    const context = cartographyContext({ wormholeDisplayMode: 'on-hover' })
    const display = buildCartographyDisplay(sampleData, context, {
      wormholeLineRevealKey: '10,20',
    })

    expect(display.edges.some((e) => e.layer === 'wormholes')).toBe(true)
  })
})
