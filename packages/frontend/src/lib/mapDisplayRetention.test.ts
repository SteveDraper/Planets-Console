import { describe, expect, it } from 'vitest'
import type { CombinedMapData } from '../api/bff'
import {
  MAP_SHELL_MAP_LOADING_MESSAGE,
  MAP_SHELL_TURN_LOADING_MESSAGE,
  deriveMapShellView,
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

describe('deriveMapShellView', () => {
  const baseInput = {
    viewMode: 'map' as const,
    displayMapData: sampleMap,
    retainDuringLoad: false,
    hasAnalyticScope: true,
    turnDataReady: true,
    turnEnsurePending: false,
    mapPending: false,
    mapHasError: false,
    mapHasAnyData: true,
  }

  it('returns ready with displayMapData when live map data is available', () => {
    expect(deriveMapShellView(baseInput)).toEqual({
      phase: 'ready',
      displayMapData: sampleMap,
    })
  })

  it('returns map-loading on initial map fetch without retention', () => {
    expect(
      deriveMapShellView({
        ...baseInput,
        displayMapData: null,
        mapPending: true,
        mapHasAnyData: false,
      })
    ).toEqual({
      phase: 'full-loading',
      loadingMessage: MAP_SHELL_MAP_LOADING_MESSAGE,
    })
  })

  it('returns retained with displayMapData while a prior frame is shown during reload', () => {
    expect(
      deriveMapShellView({
        ...baseInput,
        retainDuringLoad: true,
        mapPending: true,
        mapHasAnyData: false,
      })
    ).toEqual({
      phase: 'retained',
      displayMapData: sampleMap,
    })
  })

  it('returns error when map fetch fails without a retained frame', () => {
    expect(
      deriveMapShellView({
        ...baseInput,
        displayMapData: null,
        mapHasError: true,
        mapHasAnyData: false,
      })
    ).toEqual({ phase: 'error' })
  })

  it('returns retained (not turn-loading) during turn ensure when a prior frame is kept', () => {
    expect(
      deriveMapShellView({
        ...baseInput,
        displayMapData: sampleMap,
        retainDuringLoad: true,
        turnDataReady: false,
        turnEnsurePending: true,
        mapPending: true,
        mapHasAnyData: false,
      })
    ).toEqual({
      phase: 'retained',
      displayMapData: sampleMap,
    })
  })

  it('returns turn-loading during turn ensure when not retaining', () => {
    expect(
      deriveMapShellView({
        ...baseInput,
        displayMapData: null,
        turnDataReady: false,
        turnEnsurePending: true,
      })
    ).toEqual({
      phase: 'full-loading',
      loadingMessage: MAP_SHELL_TURN_LOADING_MESSAGE,
    })
  })

  it('returns turn-loading in tabular mode during turn ensure', () => {
    expect(
      deriveMapShellView({
        ...baseInput,
        viewMode: 'tabular',
        displayMapData: sampleMap,
        turnDataReady: false,
        turnEnsurePending: true,
      })
    ).toEqual({
      phase: 'full-loading',
      loadingMessage: MAP_SHELL_TURN_LOADING_MESSAGE,
    })
  })

  it('returns turn-loading only when analytic scope is present', () => {
    expect(
      deriveMapShellView({
        ...baseInput,
        displayMapData: null,
        hasAnalyticScope: false,
        turnDataReady: false,
        turnEnsurePending: true,
      })
    ).toEqual({
      phase: 'full-loading',
      loadingMessage: MAP_SHELL_MAP_LOADING_MESSAGE,
    })
  })

  it('returns inactive in tabular mode when not loading', () => {
    expect(
      deriveMapShellView({
        ...baseInput,
        viewMode: 'tabular',
      })
    ).toEqual({ phase: 'inactive' })
  })
})
