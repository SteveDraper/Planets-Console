import { describe, expect, it } from 'vitest'
import { connectionsMapAnalytic, connectionsMapQueryKey } from './connections/mapAnalytic'
import { fleetMapAnalytic } from './fleet/mapAnalytic'
import { stellarCartographyMapAnalytic } from './stellar-cartography/mapAnalytic'
import {
  BASE_MAP_ANALYTIC_ID,
  CONNECTIONS_ANALYTIC_ID,
  FLEET_ANALYTIC_ID,
  MAP_REGION_DEMO_ANALYTIC_ID,
  STELLAR_CARTOGRAPHY_ANALYTIC_ID,
} from './mapAnalyticIds'
import {
  defaultMapAnalyticRegistration,
  defaultMapAnalyticQuerySpec,
  defaultMapLayerMerger,
  mapAnalyticQuerySpecFor,
  mapAnalyticRegistrationFor,
  REGISTERED_MAP_ANALYTIC_IDS,
  isRegisteredMapAnalytic,
} from './mapAnalyticRegistry'
import { mapRegionDemoMapAnalytic } from './map-region-demo/mapAnalytic'
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
      FLEET_ANALYTIC_ID,
      MAP_REGION_DEMO_ANALYTIC_ID,
    ])
    for (const analyticId of REGISTERED_MAP_ANALYTIC_IDS) {
      expect(isRegisteredMapAnalytic(analyticId)).toBe(true)
    }
    expect(mapAnalyticRegistrationFor(BASE_MAP_ANALYTIC_ID)).toBe(defaultMapAnalyticRegistration)
    expect(mapAnalyticRegistrationFor(CONNECTIONS_ANALYTIC_ID)).toBe(connectionsMapAnalytic)
    expect(mapAnalyticRegistrationFor(STELLAR_CARTOGRAPHY_ANALYTIC_ID)).toBe(
      stellarCartographyMapAnalytic
    )
    expect(mapAnalyticRegistrationFor(FLEET_ANALYTIC_ID)).toBe(fleetMapAnalytic)
    expect(mapAnalyticRegistrationFor(MAP_REGION_DEMO_ANALYTIC_ID)).toBe(mapRegionDemoMapAnalytic)
  })

  it('throws for unregistered map analytics', () => {
    expect(isRegisteredMapAnalytic('unknown-analytic')).toBe(false)
    expect(() => mapAnalyticRegistrationFor('unknown-analytic')).toThrow(
      'Unregistered map analytic: unknown-analytic'
    )
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

  it('wires fleet to a disabled scaffold query spec until map layer lands', () => {
    const registration = mapAnalyticRegistrationFor(FLEET_ANALYTIC_ID)
    expect(registration).toBe(fleetMapAnalytic)
    expect(registration.buildQuerySpec).toBeDefined()
    expect(registration.mergeLayer).not.toBe(defaultMapLayerMerger)

    const spec = mapAnalyticQuerySpecFor(FLEET_ANALYTIC_ID, queryContext)
    expect(spec.queryKey).toEqual([
      'analytic',
      FLEET_ANALYTIC_ID,
      'map',
      sampleScope,
      'scaffold-v0',
    ])
    expect(spec.enabled).toBe(false)
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
