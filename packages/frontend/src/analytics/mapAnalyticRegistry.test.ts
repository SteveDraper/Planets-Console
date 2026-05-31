import { describe, expect, it } from 'vitest'
import { defaultMapAnalyticQuerySpec } from './mapAnalyticRegistry'
import { defaultConnectionsParams } from '../lib/mapAnalyticQueryTestFixtures'

describe('defaultMapAnalyticQuerySpec', () => {
  it('does not enable the query when scope is null', () => {
    const spec = defaultMapAnalyticQuerySpec('base-map', {
      analyticScope: null,
      analyticFetchEnabled: true,
      connectionsMapParams: defaultConnectionsParams,
    })

    expect(spec.enabled).toBe(false)
  })
})
