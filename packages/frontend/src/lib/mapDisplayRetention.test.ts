import { describe, expect, it } from 'vitest'
import type { CombinedMapData } from '../api/bff'
import {
  MAP_SHELL_MAP_LOADING_MESSAGE,
  MAP_SHELL_TURN_LOADING_MESSAGE,
  deriveMapShellView,
  deriveTurnEnsureLoadingView,
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
  it('retains when prior map data exists', () => {
    expect(shouldRetainMapDuringLoad(sampleMap)).toBe(true)
    expect(shouldRetainMapDuringLoad(null)).toBe(false)
  })
})

describe('deriveTurnEnsureLoadingView', () => {
  it('shows turn loading when scope is set and ensure is pending', () => {
    expect(
      deriveTurnEnsureLoadingView({
        hasAnalyticScope: true,
        turnDataReady: false,
        turnEnsurePending: true,
        suppressTurnEnsureLoading: false,
      })
    ).toEqual({ show: true, loadingMessage: MAP_SHELL_TURN_LOADING_MESSAGE })
  })

  it('suppresses turn loading while map retention keeps the prior frame', () => {
    expect(
      deriveTurnEnsureLoadingView({
        hasAnalyticScope: true,
        turnDataReady: false,
        turnEnsurePending: true,
        suppressTurnEnsureLoading: true,
      })
    ).toEqual({ show: false })
  })
})

describe('deriveMapShellView', () => {
  const baseInput = {
    displayMapData: sampleMap,
    retainDuringLoad: false,
    hasAnalyticScope: true,
    turnDataReady: true,
    turnEnsurePending: false,
    mapPending: false,
    mapHasError: false,
    mapHasAnyData: true,
  }

  it('returns showing-map with deferred pending off when live map data is available', () => {
    expect(deriveMapShellView(baseInput)).toEqual({
      phase: 'showing-map',
      displayMapData: sampleMap,
      showDeferredPending: false,
    })
  })

  it('returns showing-map with deferred pending when additional map data is loading', () => {
    expect(
      deriveMapShellView({
        ...baseInput,
        mapPending: true,
      })
    ).toEqual({
      phase: 'showing-map',
      displayMapData: sampleMap,
      showDeferredPending: true,
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

  it('returns showing-map without deferred pending while a prior frame is shown during reload', () => {
    expect(
      deriveMapShellView({
        ...baseInput,
        retainDuringLoad: true,
        mapPending: true,
        mapHasAnyData: false,
      })
    ).toEqual({
      phase: 'showing-map',
      displayMapData: sampleMap,
      showDeferredPending: false,
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

  it('returns showing-map (not turn-loading) during turn ensure when a prior frame is kept', () => {
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
      phase: 'showing-map',
      displayMapData: sampleMap,
      showDeferredPending: false,
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
})
