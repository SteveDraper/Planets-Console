import { describe, expect, it } from 'vitest'
import type { CombinedMapData } from '../api/bff'
import {
  hasDisplayableMapData,
  shouldRetainMapDuringLoad,
} from './mapDisplayRetention'

const sampleMap: CombinedMapData = {
  nodes: [{ id: 'base-map:1', label: 'A', x: 1, y: 2 }],
  edges: [],
  routeWaypoints: [],
  overlayCircles: [],
  wormholeUnknownEntrances: [],
}

describe('hasDisplayableMapData', () => {
  it('is false for null, undefined, or empty nodes', () => {
    expect(hasDisplayableMapData(null)).toBe(false)
    expect(hasDisplayableMapData(undefined)).toBe(false)
    expect(hasDisplayableMapData({ ...sampleMap, nodes: [] })).toBe(false)
  })

  it('is true when nodes are present', () => {
    expect(hasDisplayableMapData(sampleMap)).toBe(true)
  })
})

describe('shouldRetainMapDuringLoad', () => {
  it('retains only in map mode with prior map data', () => {
    expect(shouldRetainMapDuringLoad('map', sampleMap)).toBe(true)
    expect(shouldRetainMapDuringLoad('tabular', sampleMap)).toBe(false)
    expect(shouldRetainMapDuringLoad('map', null)).toBe(false)
  })
})
