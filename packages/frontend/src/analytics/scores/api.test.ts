import { describe, expect, it } from 'vitest'
import { appendScoresTableQueryParams, scoresAnalyticTableQueryKey } from './api'
import type { AnalyticShellScope } from '../../api/bff'

describe('appendScoresTableQueryParams', () => {
  it('adds includeBuildInference when enabled', () => {
    const params = new URLSearchParams({ gameId: '628580', turn: '111', perspective: '1' })
    appendScoresTableQueryParams(params, { includeBuildInference: true })
    expect(params.get('includeBuildInference')).toBe('true')
  })

  it('omits includeBuildInference when disabled', () => {
    const params = new URLSearchParams({ gameId: '628580', turn: '111', perspective: '1' })
    appendScoresTableQueryParams(params, { includeBuildInference: false })
    expect(params.get('includeBuildInference')).toBeNull()
  })
})

describe('scoresAnalyticTableQueryKey', () => {
  const scope: AnalyticShellScope = {
    gameId: '628580',
    turn: 111,
    perspective: 1,
  }

  it('includes the user includeBuildInference flag so TableTile can share the cache', () => {
    expect(scoresAnalyticTableQueryKey(scope, { includeBuildInference: true })).toEqual([
      'analytic',
      'scores',
      'table',
      scope,
      true,
    ])
    expect(scoresAnalyticTableQueryKey(scope, { includeBuildInference: false })).toEqual([
      'analytic',
      'scores',
      'table',
      scope,
      false,
    ])
  })
})
