import { describe, expect, it } from 'vitest'
import type { AnalyticItem, AnalyticShellScope, ConnectionsMapParams } from '../api/bff'
import {
  connectionsMapQueryKey,
  enabledMapAnalyticIds,
  mapIdsToFetch,
} from './useMapAnalyticQueries'

const defaultConnectionsParams: ConnectionsMapParams = {
  warpSpeed: 9,
  gravitonicMovement: false,
  flareMode: 'off',
  flareDepth: 2,
}

const sampleScope: AnalyticShellScope = {
  gameId: '628580',
  turn: 5,
  perspective: 1,
}

const sampleAnalytics: AnalyticItem[] = [
  { id: 'base-map', name: 'Base', supportsTable: false, supportsMap: true, type: 'base' },
  { id: 'connections', name: 'Connections', supportsTable: true, supportsMap: true, type: 'selectable' },
  {
    id: 'stellar-cartography',
    name: 'Stellar Cartography',
    supportsTable: false,
    supportsMap: true,
    type: 'selectable',
  },
]

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
