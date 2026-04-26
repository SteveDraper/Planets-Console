import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  fetchGames,
  INCLUDE_DIAGNOSTICS_SESSION_KEY,
  isGenericServerErrorMessage,
  normalizeMapDataResponse,
  toFetchRejectionError,
  withEndpointIfGeneric,
} from './bff'

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

describe('toFetchRejectionError', () => {
  it('includes endpoint and request path', () => {
    const e = toFetchRejectionError(
      new TypeError('Failed to fetch'),
      'GET /bff/games/1/info',
      '/bff/games/1/info'
    )
    expect(e.message).toContain('GET /bff/games/1/info')
    expect(e.message).toContain('request: /bff/games/1/info')
    expect(e.message).toContain('Failed to fetch')
    expect(e.message).toContain('No HTTP response')
  })

  it('appends Error.cause when present', () => {
    const inner = new Error('connection reset')
    const e = toFetchRejectionError(
      Object.assign(new TypeError('Failed to fetch'), { cause: inner }),
      'POST /bff/games/1/turns/ensure',
      '/bff/games/1/turns/ensure'
    )
    expect(e.message).toContain('cause:')
    expect(e.message).toContain('connection reset')
  })
})

describe('bffRequest (network failure)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    sessionStorage.removeItem(INCLUDE_DIAGNOSTICS_SESSION_KEY)
  })

  it('appends includeDiagnostics=true to /bff paths when session recording is on', async () => {
    sessionStorage.setItem(INCLUDE_DIAGNOSTICS_SESSION_KEY, '1')
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({ games: [] }), { status: 200 }))
    )
    vi.stubGlobal('fetch', fetchMock)
    await fetchGames()
    expect(fetchMock).toHaveBeenCalledWith(
      '/bff/games?includeDiagnostics=true',
      undefined
    )
  })

  it('fetchGames throws an error that names the BFF path', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    )
    await expect(fetchGames()).rejects.toSatisfy((thrown: unknown) => {
      expect(thrown).toBeInstanceOf(Error)
      const m = (thrown as Error).message
      expect(m).toMatch(/GET \/bff\/games/)
      expect(m).toMatch(/request: \/bff\/games/)
      return true
    })
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

  it('keeps flare illustrativeRoute waypointOffset and arrivalOffset when valid', () => {
    const raw = {
      analyticId: 'connections',
      nodes: [],
      edges: [],
      routes: [
        {
          fromPlanetId: 1,
          toPlanetId: 2,
          viaFlare: true,
          illustrativeRoute: [
            { kind: 'normal', to: { x: 0, y: 0 } },
            {
              kind: 'flare',
              to: { x: 3, y: 4 },
              waypointOffset: [10, 20],
              arrivalOffset: [5, -1],
            },
          ],
        },
      ],
    }
    const out = normalizeMapDataResponse(raw)
    const flare = out.routes![0].illustrativeRoute![1]
    expect(flare.waypointOffset).toEqual([10, 20])
    expect(flare.arrivalOffset).toEqual([5, -1])
  })

  it('drops illustrative steps when to.x / to.y are not finite numbers (e.g. null, empty string)', () => {
    const raw = {
      analyticId: 'connections',
      nodes: [],
      edges: [],
      routes: [
        {
          fromPlanetId: 1,
          toPlanetId: 2,
          viaFlare: true,
          illustrativeRoute: [
            { kind: 'normal', to: { x: null, y: 0 } },
            { kind: 'normal', to: { x: 5, y: 6 } },
            { kind: 'normal', to: { x: '', y: 7 } },
          ],
        },
      ],
    }
    const out = normalizeMapDataResponse(raw)
    expect(out.routes![0].illustrativeRoute).toEqual([
      { kind: 'normal', to: { x: 5, y: 6 } },
    ])
  })

  it('omits waypoint/arrival offset pairs when an element is null, empty string, or non-numeric (no coercion to 0)', () => {
    const raw: unknown = JSON.parse(
      `{
        "analyticId": "connections",
        "nodes": [],
        "edges": [],
        "routes": [
          {
            "fromPlanetId": 1,
            "toPlanetId": 2,
            "viaFlare": true,
            "illustrativeRoute": [
              {
                "kind": "flare",
                "to": { "x": 0, "y": 0 },
                "waypointOffset": [null, 1],
                "arrivalOffset": ["", 2]
              },
              { "kind": "normal", "to": { "x": 1, "y": 1 } }
            ]
          }
        ]
      }`
    )
    const out = normalizeMapDataResponse(raw)
    const step = out.routes![0].illustrativeRoute![0]
    expect(step.waypointOffset).toBeUndefined()
    expect(step.arrivalOffset).toBeUndefined()
  })

  it('accepts snake_case offset keys and omits invalid offset tuples', () => {
    const raw = {
      analyticId: 'connections',
      nodes: [],
      edges: [],
      routes: [
        {
          fromPlanetId: 1,
          toPlanetId: 2,
          viaFlare: true,
          illustrativeRoute: [
            {
              kind: 'flare',
              to: { x: 0, y: 0 },
              waypoint_offset: [1, 2],
              arrival_offset: [3, 4],
            },
            {
              kind: 'flare',
              to: { x: 1, y: 1 },
              waypointOffset: [0, Number.NaN],
            },
            {
              kind: 'normal',
              to: { x: 2, y: 2 },
            },
          ],
        },
      ],
    }
    const out = normalizeMapDataResponse(raw)
    const steps = out.routes![0].illustrativeRoute!
    expect(steps[0].waypointOffset).toEqual([1, 2])
    expect(steps[0].arrivalOffset).toEqual([3, 4])
    expect(steps[1].waypointOffset).toBeUndefined()
    expect(steps[2].waypointOffset).toBeUndefined()
  })
})
