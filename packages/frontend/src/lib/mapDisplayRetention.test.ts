import { describe, expect, it } from 'vitest'
import type { CombinedMapData } from '../api/bff'
import {
  deriveMapShellPhase,
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

describe('deriveMapShellPhase', () => {
  const baseInput = {
    viewMode: 'map' as const,
    displayMapData: sampleMap,
    retainDuringLoad: false,
    turnDataReady: true,
    turnEnsurePending: false,
    mapPending: false,
    mapHasError: false,
    mapHasAnyData: true,
  }

  it('returns ready when live map data is available', () => {
    expect(deriveMapShellPhase(baseInput)).toBe('ready')
  })

  it('returns full-loading on initial map fetch without retention', () => {
    expect(
      deriveMapShellPhase({
        ...baseInput,
        displayMapData: null,
        mapPending: true,
        mapHasAnyData: false,
      })
    ).toBe('full-loading')
  })

  it('returns retained while a prior frame is shown during reload', () => {
    expect(
      deriveMapShellPhase({
        ...baseInput,
        retainDuringLoad: true,
        mapPending: true,
        mapHasAnyData: false,
      })
    ).toBe('retained')
  })

  it('returns error when map fetch fails without a retained frame', () => {
    expect(
      deriveMapShellPhase({
        ...baseInput,
        displayMapData: null,
        mapHasError: true,
        mapHasAnyData: false,
      })
    ).toBe('error')
  })

  it('returns full-loading during turn ensure when not retaining', () => {
    expect(
      deriveMapShellPhase({
        ...baseInput,
        displayMapData: null,
        turnDataReady: false,
        turnEnsurePending: true,
      })
    ).toBe('full-loading')
  })

  it('returns full-loading in tabular mode during turn ensure', () => {
    expect(
      deriveMapShellPhase({
        ...baseInput,
        viewMode: 'tabular',
        displayMapData: sampleMap,
        turnDataReady: false,
        turnEnsurePending: true,
      })
    ).toBe('full-loading')
  })
})
