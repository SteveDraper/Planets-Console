import { describe, expect, it } from 'vitest'
import { appendConnectionsMapQueryParams, deriveIncludeIllustrativeRoutes } from './api'

describe('appendConnectionsMapQueryParams', () => {
  it('adds connections map query params and illustrative route flag when useful', () => {
    const params = new URLSearchParams({ gameId: '628580', turn: '111', perspective: '1' })
    appendConnectionsMapQueryParams(params, {
      warpSpeed: 9,
      gravitonicMovement: false,
      flareMode: 'include',
      flareDepth: 2,
    })

    expect(params.get('warpSpeed')).toBe('9')
    expect(params.get('gravitonicMovement')).toBe('false')
    expect(params.get('flareMode')).toBe('include')
    expect(params.get('flareDepth')).toBe('2')
    expect(params.get('includeIllustrativeRoutes')).toBe('true')
  })

  it('omits illustrative routes when flares are off', () => {
    const params = new URLSearchParams()
    appendConnectionsMapQueryParams(params, {
      warpSpeed: 8,
      gravitonicMovement: true,
      flareMode: 'off',
      flareDepth: 3,
    })

    expect(params.get('includeIllustrativeRoutes')).toBeNull()
  })

  it('deriveIncludeIllustrativeRoutes matches Core transport rule', () => {
    expect(deriveIncludeIllustrativeRoutes('off', 3)).toBe(false)
    expect(deriveIncludeIllustrativeRoutes('include', 1)).toBe(false)
    expect(deriveIncludeIllustrativeRoutes('include', 2)).toBe(true)
    expect(deriveIncludeIllustrativeRoutes('only', 2)).toBe(true)
  })
})
