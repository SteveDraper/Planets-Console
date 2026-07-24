import { describe, expect, it } from 'vitest'
import type { AnalyticItem } from '../api/bff'
import { enabledMapAnalyticIds, enabledTableAnalyticIds } from './enabledModeAnalyticIds'

const sampleAnalytics: AnalyticItem[] = [
  { id: 'base-map', name: 'Base', supportsTable: false, supportsMap: true, type: 'base' },
  {
    id: 'connections',
    name: 'Connections',
    supportsTable: false,
    supportsMap: true,
    type: 'selectable',
  },
  {
    id: 'scores',
    name: 'Scores',
    supportsTable: true,
    supportsMap: false,
    type: 'selectable',
  },
  {
    id: 'stellar-cartography',
    name: 'Stellar Cartography',
    supportsTable: false,
    supportsMap: true,
    type: 'selectable',
  },
  {
    id: 'fleet',
    name: 'Fleet',
    supportsTable: true,
    supportsMap: true,
    type: 'selectable',
  },
]

describe('enabledTableAnalyticIds', () => {
  it('keeps only analytics with supportsTable', () => {
    expect(
      enabledTableAnalyticIds(
        ['connections', 'scores', 'stellar-cartography', 'fleet'],
        sampleAnalytics
      )
    ).toEqual(['scores', 'fleet'])
  })

  it('returns empty when only map-only analytics are enabled', () => {
    expect(
      enabledTableAnalyticIds(['connections', 'stellar-cartography'], sampleAnalytics)
    ).toEqual([])
  })

  it('preserves enabled order among table-supported ids', () => {
    expect(enabledTableAnalyticIds(['fleet', 'scores'], sampleAnalytics)).toEqual([
      'fleet',
      'scores',
    ])
  })
})

describe('enabledMapAnalyticIds', () => {
  it('keeps selectable map analytics and excludes base-map', () => {
    expect(
      enabledMapAnalyticIds(
        ['base-map', 'connections', 'scores', 'stellar-cartography', 'fleet'],
        sampleAnalytics
      )
    ).toEqual(['connections', 'stellar-cartography', 'fleet'])
  })

  it('preserves enabled order among map-supported ids', () => {
    expect(enabledMapAnalyticIds(['fleet', 'connections'], sampleAnalytics)).toEqual([
      'fleet',
      'connections',
    ])
  })
})
