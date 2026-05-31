import { describe, expect, it } from 'vitest'
import {
  combineMapResultsFromQueries,
  connectionsMapQueryKey,
  enabledMapAnalyticIds,
  mapIdsToFetch,
} from './useMapAnalyticQueries'
import {
  defaultConnectionsParams,
  sampleAnalytics,
  sampleScope,
} from './mapAnalyticQueryTestFixtures'

describe('combineMapResultsFromQueries', () => {
  it('merges map payloads in analytic id order', () => {
    const combined = combineMapResultsFromQueries(
      ['base-map', 'connections'],
      [
        {
          analyticId: 'base-map',
          nodes: [{ id: '1', label: 'A', x: 0, y: 0 }],
          edges: [],
        },
        {
          analyticId: 'connections',
          nodes: [],
          edges: [],
          routes: [],
        },
      ],
      { liveConnectionsParams: null, futureTurnOffset: 0 }
    )
    expect(combined.nodes).toHaveLength(1)
    expect(combined.nodes[0].id).toBe('base-map:1')
  })
})

describe('connectionsMapQueryKey', () => {
  it('uses null scope fields when scope is unset', () => {
    expect(connectionsMapQueryKey(null, defaultConnectionsParams)).toEqual([
      'analytic',
      'connections',
      'map',
      null,
      null,
      null,
      9,
      false,
      'off',
      2,
    ])
  })

  it('embeds scope and connection params when scope is set', () => {
    expect(connectionsMapQueryKey(sampleScope, defaultConnectionsParams)).toEqual([
      'analytic',
      'connections',
      'map',
      '628580',
      5,
      1,
      9,
      false,
      'off',
      2,
    ])
  })
})

describe('enabledMapAnalyticIds and mapIdsToFetch', () => {
  it('includes base map first and skips duplicate base id in enabled list', () => {
    const enabled = enabledMapAnalyticIds(
      ['connections', 'base-map', 'stellar-cartography'],
      sampleAnalytics
    )
    expect(enabled).toEqual(['connections', 'stellar-cartography'])
    expect(mapIdsToFetch(sampleAnalytics, enabled)).toEqual([
      'base-map',
      'connections',
      'stellar-cartography',
    ])
  })
})
