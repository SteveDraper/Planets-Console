import { describe, expect, it } from 'vitest'
import { connectionsMapAnalytic, connectionsMapQueryKey } from './connections/mapAnalytic'
import { stellarCartographyMapAnalytic } from './stellar-cartography/mapAnalytic'
import {
  BASE_MAP_ANALYTIC_ID,
  CONNECTIONS_ANALYTIC_ID,
  STELLAR_CARTOGRAPHY_ANALYTIC_ID,
} from './mapAnalyticIds'
import {
  defaultMapAnalyticRegistration,
  defaultMapAnalyticQuerySpec,
  defaultMapLayerMerger,
  enabledMapIdsRequireLiveMapContext,
  mapAnalyticQuerySpecFor,
  mapAnalyticRegistrationFor,
  mapAnalyticRequiresLiveMapContext,
  REGISTERED_MAP_ANALYTIC_IDS,
  isRegisteredMapAnalytic,
} from './mapAnalyticRegistry'
import {
  defaultConnectionsParams,
  sampleScope,
} from '../lib/mapAnalyticQueryTestFixtures'

const queryContext = {
  analyticScope: sampleScope,
  analyticFetchEnabled: true,
  connectionsMapParams: defaultConnectionsParams,
}

describe('map analytic registry', () => {
  it('registers every canonical map analytic id explicitly', () => {
    expect(REGISTERED_MAP_ANALYTIC_IDS).toEqual([
      BASE_MAP_ANALYTIC_ID,
      CONNECTIONS_ANALYTIC_ID,
      STELLAR_CARTOGRAPHY_ANALYTIC_ID,
    ])
    for (const analyticId of REGISTERED_MAP_ANALYTIC_IDS) {
      expect(isRegisteredMapAnalytic(analyticId)).toBe(true)
    }
    expect(mapAnalyticRegistrationFor(BASE_MAP_ANALYTIC_ID)).toBe(defaultMapAnalyticRegistration)
    expect(mapAnalyticRegistrationFor(CONNECTIONS_ANALYTIC_ID)).toBe(connectionsMapAnalytic)
    expect(mapAnalyticRegistrationFor(STELLAR_CARTOGRAPHY_ANALYTIC_ID)).toBe(
      stellarCartographyMapAnalytic
    )
  })

  it('uses default registration for unknown analytics', () => {
    expect(isRegisteredMapAnalytic('unknown-analytic')).toBe(false)
    expect(mapAnalyticRegistrationFor('unknown-analytic')).toBe(defaultMapAnalyticRegistration)
    expect(mapAnalyticRegistrationFor('unknown-analytic').mergeLayer).toBe(defaultMapLayerMerger)
  })

  it('wires base map to the default query spec and prefix merger', () => {
    const registration = mapAnalyticRegistrationFor(BASE_MAP_ANALYTIC_ID)
    expect(registration.buildQuerySpec).toBeUndefined()
    expect(registration.mergeLayer).toBe(defaultMapLayerMerger)

    const spec = mapAnalyticQuerySpecFor(BASE_MAP_ANALYTIC_ID, queryContext)
    expect(spec.queryKey).toEqual([
      'analytic',
      BASE_MAP_ANALYTIC_ID,
      'map',
      sampleScope,
      'planet-v2',
    ])
    expect(spec.enabled).toBe(true)
  })

  it('wires connections to a parametric query spec and custom merger', () => {
    const registration = mapAnalyticRegistrationFor(CONNECTIONS_ANALYTIC_ID)
    expect(registration).toBe(connectionsMapAnalytic)
    expect(registration.buildQuerySpec).toBeDefined()
    expect(registration.mergeLayer).not.toBe(defaultMapLayerMerger)

    const spec = mapAnalyticQuerySpecFor(CONNECTIONS_ANALYTIC_ID, queryContext)
    expect(spec.queryKey).toEqual(
      connectionsMapQueryKey(sampleScope, defaultConnectionsParams)
    )
    expect(spec.enabled).toBe(true)
  })

  it('wires stellar cartography to the default query spec and custom merger', () => {
    const registration = mapAnalyticRegistrationFor(STELLAR_CARTOGRAPHY_ANALYTIC_ID)
    expect(registration).toBe(stellarCartographyMapAnalytic)
    expect(registration.requiresLiveMapContext).toBe(true)
    expect(mapAnalyticRequiresLiveMapContext(STELLAR_CARTOGRAPHY_ANALYTIC_ID)).toBe(true)
    expect(mapAnalyticRequiresLiveMapContext(CONNECTIONS_ANALYTIC_ID)).toBe(false)
    expect(
      enabledMapIdsRequireLiveMapContext([CONNECTIONS_ANALYTIC_ID, STELLAR_CARTOGRAPHY_ANALYTIC_ID])
    ).toBe(true)
    expect(registration.buildQuerySpec).toBeUndefined()
    expect(registration.mergeLayer).not.toBe(defaultMapLayerMerger)

    const spec = mapAnalyticQuerySpecFor(STELLAR_CARTOGRAPHY_ANALYTIC_ID, queryContext)
    expect(spec.queryKey).toEqual([
      'analytic',
      STELLAR_CARTOGRAPHY_ANALYTIC_ID,
      'map',
      sampleScope,
      'planet-v2',
    ])
  })
})

describe('defaultMapAnalyticQuerySpec', () => {
  it('does not enable the query when scope is null', () => {
    const spec = defaultMapAnalyticQuerySpec(BASE_MAP_ANALYTIC_ID, {
      analyticScope: null,
      analyticFetchEnabled: true,
      connectionsMapParams: defaultConnectionsParams,
    })

    expect(spec.enabled).toBe(false)
  })
})
