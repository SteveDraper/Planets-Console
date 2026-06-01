import { describe, expect, it } from 'vitest'
import {
  MAP_SHELL_MAP_LOADING_MESSAGE,
  MAP_SHELL_TURN_LOADING_MESSAGE,
  deriveMapShellView,
  deriveTurnEnsureLoadingView,
  hasDisplayableMapData,
} from './mapDisplayRetention'
import { sampleMap } from './mapDisplayTestFixtures'

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

describe('deriveTurnEnsureLoadingView', () => {
  it('shows turn loading when scope is set and ensure is pending', () => {
    expect(
      deriveTurnEnsureLoadingView({
        hasAnalyticScope: true,
        turnDataReady: false,
        turnEnsurePending: true,
      })
    ).toEqual({ show: true, loadingMessage: MAP_SHELL_TURN_LOADING_MESSAGE })
  })

  it('does not show turn loading when scope is unset or ensure is idle', () => {
    expect(
      deriveTurnEnsureLoadingView({
        hasAnalyticScope: false,
        turnDataReady: false,
        turnEnsurePending: true,
      })
    ).toEqual({ show: false })
    expect(
      deriveTurnEnsureLoadingView({
        hasAnalyticScope: true,
        turnDataReady: true,
        turnEnsurePending: false,
      })
    ).toEqual({ show: false })
  })
})

describe('deriveMapShellView', () => {
  const baseInput = {
    frame: { source: 'live', data: sampleMap } as const,
    hasAnalyticScope: true,
    turnDataReady: true,
    turnEnsurePending: false,
    mapPending: false,
    mapHasError: false,
    mapHasAnyData: true,
    mapError: null,
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
        frame: { source: 'none' },
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
        frame: { source: 'retained', data: sampleMap },
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
    const err = new Error('map failed')
    expect(
      deriveMapShellView({
        ...baseInput,
        frame: { source: 'none' },
        mapHasError: true,
        mapHasAnyData: false,
        mapError: err,
      })
    ).toEqual({ phase: 'error', error: err })
  })

  it('returns showing-map (not turn-loading) during turn ensure when a prior frame is kept', () => {
    expect(
      deriveMapShellView({
        ...baseInput,
        frame: { source: 'retained', data: sampleMap },
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
        frame: { source: 'none' },
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
        frame: { source: 'none' },
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
