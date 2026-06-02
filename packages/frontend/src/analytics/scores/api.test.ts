import { describe, expect, it } from 'vitest'
import { appendScoresTableQueryParams } from './api'

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
