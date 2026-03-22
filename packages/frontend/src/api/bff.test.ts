import { describe, it, expect } from 'vitest'
import { isGenericServerErrorMessage, normalizeMapDataResponse, withEndpointIfGeneric } from './bff'

describe('withEndpointIfGeneric', () => {
  it('appends endpoint for Internal Server Error', () => {
    expect(
      withEndpointIfGeneric('Internal Server Error', 'POST /bff/games/1/info')
    ).toBe('Internal Server Error (POST /bff/games/1/info)')
  })

  it('does not append for specific API messages', () => {
    expect(
      withEndpointIfGeneric('Login credentials are required.', 'POST /bff/games/1/info')
    ).toBe('Login credentials are required.')
  })

  it('appends for bare 500 status message', () => {
    expect(withEndpointIfGeneric('500', 'GET /bff/games')).toBe('500 (GET /bff/games)')
  })

  it('does not append for 404', () => {
    expect(withEndpointIfGeneric('404', 'GET /bff/games')).toBe('404')
  })

  it('does not duplicate endpoint if already present', () => {
    expect(
      withEndpointIfGeneric('500 (GET /bff/games)', 'GET /bff/games')
    ).toBe('500 (GET /bff/games)')
  })
})

describe('isGenericServerErrorMessage', () => {
  it('treats empty as generic', () => {
    expect(isGenericServerErrorMessage('')).toBe(true)
  })
})

describe('normalizeMapDataResponse', () => {
  it('copies planet onto each node as a plain object', () => {
    const raw = {
      analyticId: 'base-map',
      nodes: [
        {
          id: 'p1',
          label: 'p1',
          x: 10,
          y: 20,
          planet: { id: 1, name: 'Homeworld' },
          ownerName: null,
        },
      ],
      edges: [],
    }
    const out = normalizeMapDataResponse(raw)
    expect(out.nodes[0].planet).toEqual({ id: 1, name: 'Homeworld' })
    expect(out.nodes[0].planet).not.toBe((raw.nodes[0] as { planet: object }).planet)
  })

  it('reads nested snapshot from Planet key when planet is absent', () => {
    const raw = {
      analyticId: 'base-map',
      nodes: [{ id: 'p2', label: 'p2', x: 0, y: 0, Planet: { id: 2, name: 'Alt' } }],
      edges: [],
    }
    const out = normalizeMapDataResponse(raw)
    expect(out.nodes[0].planet?.name).toBe('Alt')
  })
})
