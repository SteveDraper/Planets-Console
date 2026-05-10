import { describe, expect, it } from 'vitest'
import { combineMapData } from './mapLayers'
import type { MapDataResponse } from '../api/bff'

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

    const combined = combineMapData(
      ['base-map', 'connections'],
      [{ data: baseMap }, { data: connections }],
      null
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
        warpSpeed: 9,
        gravitonicMovement: false,
        flareMode: 'only',
        flareDepth: 2,
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
})
