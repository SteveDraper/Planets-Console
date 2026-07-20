import { describe, expect, it } from 'vitest'
import type { MapDataResponse } from '../api/bff'
import { combineMapData } from './mapLayers'
import { defaultStellarCartographyMapUiConfig } from './stellar-cartography/mapUiConfig'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from './stellar-cartography/layers'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
} from './stellar-cartography/clusterOutlineDisplayMode'
import { cartographyVisibilityPolicy } from './stellar-cartography/cartographyVisibilityPolicy'

describe('combineMapData', () => {
  const baseMap: MapDataResponse = {
    analyticId: 'base-map',
    nodes: [
      { id: 'p1', label: 'p1', x: 10, y: 20 },
      { id: 'p2', label: 'p2', x: 30, y: 40 },
    ],
    edges: [],
  }

  it('binds Connections routes onto base-map planet node ids', () => {
    const connections: MapDataResponse = {
      analyticId: 'connections',
      nodes: [],
      edges: [],
      routes: [{ fromPlanetId: 1, toPlanetId: 2, viaFlare: false }],
    }

    const combined = combineMapData(['base-map', 'connections'], [baseMap, connections], {
      liveConnectionsParams: null,
    })

    expect(combined.edges).toContainEqual({
      source: 'base-map:p1',
      target: 'base-map:p2',
      viaFlare: false,
    })
  })

  it('filters flare routes according to live Connections params', () => {
    const connections: MapDataResponse = {
      analyticId: 'connections',
      nodes: [],
      edges: [],
      routes: [
        { fromPlanetId: 1, toPlanetId: 2, viaFlare: false },
        { fromPlanetId: 2, toPlanetId: 3, viaFlare: true },
      ],
    }

    const combined = combineMapData(
      ['base-map', 'connections'],
      [baseMap, connections],
      {
        liveConnectionsParams: {
          warpSpeed: 9,
          gravitonicMovement: false,
          flareMode: 'only',
          flareDepth: 2,
        },
      }
    )

    expect(combined.edges).toEqual([
      {
        source: 'base-map:p2',
        target: 'base-map:p3',
        viaFlare: true,
      },
    ])
  })

  it('keeps normalWellCells on combined base-map nodes for the warp-well overlay', () => {
    const cells = [{ x: 10, y: 20 }]
    const baseMapWithWells: MapDataResponse = {
      analyticId: 'base-map',
      nodes: [
        {
          id: 'p1',
          label: 'p1',
          x: 10,
          y: 20,
          planet: { id: 1, debrisdisk: 0 },
          normalWellCells: cells,
        },
      ],
      edges: [],
    }

    const combined = combineMapData(['base-map'], [baseMapWithWells], {
      liveConnectionsParams: null,
    })
    expect(combined.nodes[0].normalWellCells).toEqual(cells)
  })

  it('clones planet snapshots when prefixing base-map nodes', () => {
    const planet = { id: 1, name: 'Homeworld', temp: 50 }
    const baseMapWithPlanet: MapDataResponse = {
      analyticId: 'base-map',
      nodes: [{ id: 'p1', label: 'p1', x: 10, y: 20, planet }],
      edges: [],
    }

    const combined = combineMapData(['base-map'], [baseMapWithPlanet], {
      liveConnectionsParams: null,
    })
    expect(combined.nodes[0].planet).toEqual(planet)
    expect(combined.nodes[0].planet).not.toBe(planet)
  })

  it('merges stellar cartography wormhole nodes and bidirectional edges from wire data', () => {
    const sc: MapDataResponse = {
      analyticId: 'stellar-cartography',
      nodes: [
        { id: 'wh-1', label: '', x: 10, y: 10 },
        { id: 'wh-2', label: '', x: 20, y: 20 },
      ],
      edges: [
        {
          source: 'wh-1',
          target: 'wh-2',
          layer: 'wormholes',
          isBidirectional: true,
          stability: 80,
          name: 'A',
        },
      ],
      overlayCircles: [],
    }

    const combined = combineMapData(
      ['base-map', 'stellar-cartography'],
      [baseMap, sc],
      { liveConnectionsParams: null }
    )

    expect(combined.nodes.map((n) => n.id)).toEqual([
      'base-map:p1',
      'base-map:p2',
      'stellar-cartography:wh-1',
      'stellar-cartography:wh-2',
    ])
    expect(combined.edges).toHaveLength(1)
    expect(combined.edges[0]).toMatchObject({
      source: 'stellar-cartography:wh-1',
      target: 'stellar-cartography:wh-2',
      layer: 'wormholes',
      isBidirectional: true,
      sourceGameX: 10,
      sourceGameY: 10,
      targetGameX: 20,
      targetGameY: 20,
    })
  })

  it('merges all overlay circles from wire data regardless of UI visibility', () => {
    const sc: MapDataResponse = {
      analyticId: 'stellar-cartography',
      nodes: [],
      edges: [],
      overlayCircles: [
        {
          layer: 'nebulae',
          id: 'neb-1',
          x: 1,
          y: 2,
          radius: 10,
          name: 'Zoie',
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
    }

    const combined = combineMapData(['stellar-cartography'], [sc], {
      liveConnectionsParams: null,
    })

    expect(combined.overlayCircles).toHaveLength(2)
  })

  it('merges region overlays from the map-region-demo analytic', () => {
    const demo: MapDataResponse = {
      analyticId: 'map-region-demo',
      nodes: [],
      edges: [],
      regionOverlays: [
        {
          kind: 'demo',
          id: 'demo-coverage',
          fillColor: '#22c55e',
          fillOpacity: 0.25,
          disks: [{ x: 10, y: 20, radius: 150 }],
          patches: [],
        },
      ],
    }

    const combined = combineMapData(['map-region-demo'], [demo], {
      liveConnectionsParams: null,
    })

    expect(combined.regionOverlays).toHaveLength(1)
    expect(combined.regionOverlays[0]).toMatchObject({
      kind: 'demo',
      fillColor: '#22c55e',
      disks: [{ x: 10, y: 20, radius: 150 }],
    })
  })

  it('records unknown-target wormhole entrances when no edge is emitted', () => {
    const sc: MapDataResponse = {
      analyticId: 'stellar-cartography',
      nodes: [{ id: 'wh-9', label: '', x: 99, y: 88 }],
      edges: [],
      overlayCircles: [],
    }

    const combined = combineMapData(['stellar-cartography'], [sc], {
      liveConnectionsParams: null,
    })

    expect(combined.wormholeUnknownEntrances).toEqual([{ x: 99, y: 88 }])
  })

  it('extrapolates ion storm overlay positions for future turns', () => {
    const sc: MapDataResponse = {
      analyticId: 'stellar-cartography',
      nodes: [],
      edges: [],
      overlayCircles: [
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
          x: 100,
          y: 200,
          radius: 30,
          class: 2,
          heading: 0,
          warp: 5,
        },
      ],
    }

    const combined = combineMapData(['stellar-cartography'], [sc], {
      liveConnectionsParams: null,
    })

    expect(combined.overlayCircles[0]).toMatchObject({ layer: 'nebulae', x: 1, y: 2 })
    expect(combined.overlayCircles[1]).toMatchObject({ layer: 'ion-storms', x: 100, y: 200 })
  })
})

describe('cartography display filters (render-time)', () => {
  const uiConfig = {
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

  it('hides overlay circles when layer visibility is off', () => {
    const filtered = cartographyVisibilityPolicy({
      ...uiConfig,
      layerVisibility: {
        ...uiConfig.layerVisibility,
        nebulae: false,
      },
    }).overlayCircles([
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

    expect(filtered).toHaveLength(1)
    expect(filtered[0]?.layer).toBe('ion-storms')
  })

  it('hides wormhole geometry at render time when display mode is off', () => {
    expect(
      cartographyVisibilityPolicy({
        ...uiConfig,
        wormholeDisplayMode: 'off',
      }).areWormholesShown()
    ).toBe(false)
  })
})
