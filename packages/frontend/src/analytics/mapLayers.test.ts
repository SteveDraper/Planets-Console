import { describe, expect, it } from 'vitest'
import { combineMapData } from './mapLayers'
import type { MapDataResponse } from '../api/bff'
import { defaultCartographyLayerVisibility, EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from './stellar-cartography/layers'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
} from './stellar-cartography/clusterOutlineDisplayMode'

describe('combineMapData', () => {
  const baseMap: MapDataResponse = {
    analyticId: 'base-map',
    nodes: [
      { id: 'p1', label: 'p1', x: 10, y: 20 },
      { id: 'p2', label: 'p2', x: 30, y: 40 },
    ],
    edges: [],
  }

  const cartographyOptions = {
    liveConnectionsParams: null,
    stellarCartography: {
      layerVisibility: defaultCartographyLayerVisibility(),
      settingsGates: {
        ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
        debrisDiskBorders: true,
        nebulae: true,
        ionStorms: true,
        starClusters: true,
        wormholes: true,
        blackHoles: true,
      },
      wormholeDisplayMode: 'always' as const,
      starClusterDisplayMode: defaultStarClusterDisplayMode(),
      neutronClusterDisplayMode: defaultNeutronClusterDisplayMode(),
    },
  }

  it('binds Connections routes onto base-map planet node ids', () => {
    const connections: MapDataResponse = {
      analyticId: 'connections',
      nodes: [],
      edges: [],
      routes: [{ fromPlanetId: 1, toPlanetId: 2, viaFlare: false }],
    }

    const combined = combineMapData(
      ['base-map', 'connections'],
      [{ data: baseMap }, { data: connections }],
      {
        liveConnectionsParams: null,
      }
    )

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
      [{ data: baseMap }, { data: connections }],
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

    const combined = combineMapData(['base-map'], [{ data: baseMapWithWells }], {
      liveConnectionsParams: null,
    })
    expect(combined.nodes[0].normalWellCells).toEqual(cells)
  })

  it('prefixes stellar cartography wormhole nodes and merges bidirectional edges once', () => {
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
      [{ data: baseMap }, { data: sc }],
      cartographyOptions
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

  it('filters overlay circles by layer visibility and settings gates', () => {
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

    const combined = combineMapData(
      ['stellar-cartography'],
      [{ data: sc }],
      {
        ...cartographyOptions,
        stellarCartography: {
          ...cartographyOptions.stellarCartography,
          layerVisibility: {
            ...defaultCartographyLayerVisibility(),
            nebulae: false,
          },
        },
      }
    )

    expect(combined.overlayCircles).toHaveLength(1)
    expect(combined.overlayCircles[0].layer).toBe('ion-storms')
  })

  it('passes debris disk borders when layer and gate are enabled', () => {
    const sc: MapDataResponse = {
      analyticId: 'stellar-cartography',
      nodes: [],
      edges: [],
      overlayCircles: [
        {
          layer: 'debris-disks',
          id: 'dd-1',
          x: 100,
          y: 200,
          radius: 37,
        },
      ],
    }

    const combined = combineMapData(['stellar-cartography'], [{ data: sc }], cartographyOptions)

    expect(combined.overlayCircles).toHaveLength(1)
    expect(combined.overlayCircles[0].layer).toBe('debris-disks')
  })

  it('filters debris disk borders when the settings gate is off', () => {
    const sc: MapDataResponse = {
      analyticId: 'stellar-cartography',
      nodes: [],
      edges: [],
      overlayCircles: [
        {
          layer: 'debris-disks',
          id: 'dd-1',
          x: 100,
          y: 200,
          radius: 37,
        },
      ],
    }

    const combined = combineMapData(
      ['stellar-cartography'],
      [{ data: sc }],
      {
        ...cartographyOptions,
        stellarCartography: {
          ...cartographyOptions.stellarCartography,
          settingsGates: {
            ...cartographyOptions.stellarCartography.settingsGates,
            debrisDiskBorders: false,
          },
        },
      }
    )

    expect(combined.overlayCircles).toHaveLength(0)
  })

  it('records unknown-target wormhole entrances when no edge is emitted', () => {
    const sc: MapDataResponse = {
      analyticId: 'stellar-cartography',
      nodes: [{ id: 'wh-9', label: '', x: 99, y: 88 }],
      edges: [],
      overlayCircles: [],
    }

    const combined = combineMapData(['stellar-cartography'], [{ data: sc }], cartographyOptions)

    expect(combined.wormholeUnknownEntrances).toEqual([{ x: 99, y: 88 }])
  })

  it('omits wormhole geometry when display mode is off', () => {
    const sc: MapDataResponse = {
      analyticId: 'stellar-cartography',
      nodes: [
        { id: 'wh-a', label: '', x: 1, y: 2 },
        { id: 'wh-b', label: '', x: 9, y: 8 },
      ],
      edges: [
        {
          source: 'wh-a',
          target: 'wh-b',
          isBidirectional: true,
          stability: 80,
        },
      ],
      overlayCircles: [],
    }

    const combined = combineMapData(
      ['stellar-cartography'],
      [{ data: sc }],
      {
        ...cartographyOptions,
        stellarCartography: {
          ...cartographyOptions.stellarCartography,
          wormholeDisplayMode: 'off',
        },
      }
    )

    expect(combined.edges.filter((edge) => edge.layer === 'wormholes')).toHaveLength(0)
    expect(combined.wormholeUnknownEntrances).toHaveLength(0)
  })

  it('omits star cluster overlay circles when display mode is off', () => {
    const sc: MapDataResponse = {
      analyticId: 'stellar-cartography',
      nodes: [],
      edges: [],
      overlayCircles: [
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
    }

    const combined = combineMapData(
      ['stellar-cartography'],
      [{ data: sc }],
      {
        ...cartographyOptions,
        stellarCartography: {
          ...cartographyOptions.stellarCartography,
          starClusterDisplayMode: 'off',
        },
      }
    )

    expect(combined.overlayCircles).toHaveLength(0)
  })

  it('requires Stellar Cartography merge options when merging that layer', () => {
    const sc: MapDataResponse = {
      analyticId: 'stellar-cartography',
      nodes: [],
      edges: [],
      overlayCircles: [],
    }

    expect(() =>
      combineMapData(['stellar-cartography'], [{ data: sc }], { liveConnectionsParams: null })
    ).toThrow('Stellar Cartography map merge requires stellarCartography options')
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

    const combined = combineMapData(['stellar-cartography'], [{ data: sc }], {
      ...cartographyOptions,
      futureTurnOffset: 2,
    })

    expect(combined.overlayCircles[0]).toMatchObject({ layer: 'nebulae', x: 1, y: 2 })
    expect(combined.overlayCircles[1]).toMatchObject({ layer: 'ion-storms', x: 100, y: 250 })
  })
})
